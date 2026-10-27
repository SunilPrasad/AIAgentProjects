"""Stage 2 - Research: three Scouts research the book's topic, each from its own angle.

Each Scout:
  1. plans a few web search queries for its angle (AI, JSON)
  2. runs them on the profile's search provider (falling back to the fallback provider),
     plus the free scholarly sources for evidence books
  3. reads the pages it found (when the search only gave a snippet)
  4. writes research notes where every fact cites a numbered source, e.g. [S4] (AI)

The Scouts run at the same time and share one numbered source list. If a Scout fails,
the others still produce a brief. The results on disk:

    research/sources.json        every source with its quality score (you can exclude any)
    research/notes-scout-N.md    each Scout's raw notes
    research/topic.md            the research brief: all notes + the source list
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Awaitable, Callable

from bookguild import prompts, storage
from bookguild.events import EventBus, Status
from bookguild.gateway import AIGateway
from bookguild.models import SEARCH_PROVIDERS, ModelProfile
from bookguild.profile import BookProfile
from bookguild.reliability import Failure, LLMError, PermanentError, RetryPolicy, with_retries
from bookguild.research.search import SearchClient, SearchHit
from bookguild.research.sources import (
    HIGH_QUALITY,
    Source,
    SourceRegistry,
    load_sources,
    remove_excluded_citations,
    research_texts_for_prompt,
    save_sources,
    score_source,
    source_list_markdown,
)
from bookguild.storage import Book

SCOUT_ANGLES = {
    "Scout-1": "core facts - the main people, events, dates and what actually happened",
    "Scout-2": "explanations - the ideas, science and context a reader needs to understand the topic",
    "Scout-3": "human details - lesser-known facts, documented anecdotes and vivid, verifiable stories",
}
QUERIES_PER_SCOUT = 4
RESULTS_PER_QUERY = 4
SCHOLARLY_QUERIES = 2  # how many of each Scout's queries also go to Wikipedia / OpenAlex / Crossref
PAGES_TO_READ = 8  # snippet-only sources whose pages a Scout fetches and reads
SOURCES_PER_SCOUT = 10  # best sources given to a Scout for its notes
NOTES_MAX_TOKENS = 5000

TOPIC_FILE = "research/topic.md"


@dataclass
class ResearchJob:
    """Everything the stage needs, passed in by BookSession."""

    book: Book
    profile: BookProfile
    gateway: AIGateway
    models: ModelProfile
    search: SearchClient
    bus: EventBus
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    sleep: Callable[[float], Awaitable] = asyncio.sleep
    stage: str = "research"  # "chapters" when a Scout researches a single chapter


@dataclass
class ScoutReport:
    scout: str
    queries: list[str]
    source_ids: list[str]
    notes: str


async def run(job: ResearchJob) -> tuple[list[ScoutReport], list[str]]:
    """Run all Scouts. Returns (reports of the Scouts that succeeded, error messages of those that failed)."""
    registry = SourceRegistry()
    primary, fallback = choose_providers(job)
    results = await asyncio.gather(
        *(run_scout(job, scout, angle, registry, primary, fallback) for scout, angle in SCOUT_ANGLES.items()),
        return_exceptions=True,
    )

    reports, errors = [], []
    for scout, result in zip(SCOUT_ANGLES, results):
        if isinstance(result, LLMError):
            errors.append(f"{scout}: {result.message}")
        elif isinstance(result, Exception):
            raise result  # a programming error - don't hide it
        else:
            reports.append(result)
            notes_path = job.book.folder / f"research/notes-{scout.lower()}.md"
            notes_path.parent.mkdir(exist_ok=True)
            notes_path.write_text(result.notes, encoding="utf-8")

    save_sources(job.book, registry.all())
    if reports:
        write_topic_brief(job.book, job.profile)
    return reports, errors


def choose_providers(job: ResearchJob) -> tuple[str, str | None]:
    """(provider to use first, fallback or None). Skips a provider whose API key is missing."""
    primary, fallback = job.models.search, job.models.search_fallback
    if not job.search.has_key(primary):
        label = SEARCH_PROVIDERS[primary].label
        job.bus.log(f"No API key for {label} - using {SEARCH_PROVIDERS[fallback].label} instead. "
                    "Results will be weaker for evidence books.", "warning", job.stage, "Scout-1")
        return fallback, None
    return primary, (fallback if fallback != primary and job.search.has_key(fallback) else None)


async def run_scout(job: ResearchJob, scout: str, angle: str, registry: SourceRegistry,
                    primary: str, fallback: str | None) -> ScoutReport:
    bus = job.bus
    queries = await plan_queries(job, scout, angle)
    bus.log(f"Queries: {' | '.join(queries)}", stage=job.stage, agent=scout)

    found: list[Source] = []
    for number, query in enumerate(queries, start=1):
        bus.set_agent_status(scout, Status.RUNNING, f"searching {number}/{len(queries)}", job.stage)
        hits = await web_search(job, scout, query, primary, fallback)
        if job.profile.mode == "evidence" and number <= SCHOLARLY_QUERIES:
            hits += await job.search.scholarly_search(query)
        for hit in hits:
            source = registry.add(hit, scout, query)
            if source is not None and not source.excluded and source not in found:  # you excluded it
                found.append(source)

    bus.set_agent_status(scout, Status.RUNNING, "reading pages", job.stage)
    await read_pages(job, sorted(found, key=lambda s: -s.quality))
    best = sorted(found, key=lambda s: (s.quality + (10 if s.full_text else 0)), reverse=True)[:SOURCES_PER_SCOUT]
    if not best:
        error = PermanentError("found no usable sources", use_fallback=False)
        bus.set_agent_status(scout, Status.FAILED, "no sources", job.stage)
        bus.log("FAILED: found no usable sources for its queries", "error", job.stage, scout)
        bus.failure_added.emit(Failure(stage=job.stage, agent=scout, model=primary, error=error.message,
                                       kind="permanent", attempts=1, retry=job.gateway.step_retry))
        raise error

    high = sum(1 for s in best if s.quality >= HIGH_QUALITY)
    bus.log(f"Using {len(best)} sources ({high} high quality, {sum(s.full_text for s in best)} full pages)",
            stage=job.stage, agent=scout)
    notes = await write_notes(job, scout, angle, best)
    return ScoutReport(scout=scout, queries=queries, source_ids=[s.id for s in best], notes=notes)


async def plan_queries(job: ResearchJob, scout: str, angle: str) -> list[str]:
    prompt = prompts.render("scout_queries", scout=scout, angle=angle, profile=job.profile.for_prompt(),
                            brief=storage.read_brief(job.book), count=str(QUERIES_PER_SCOUT))
    result = await job.gateway.chat_json(
        agent=scout, stage=job.stage, model=job.models.model_for(scout), fallback_model=job.models.fallback,
        messages=[{"role": "user", "content": prompt}], max_tokens=1000, thinking="off", required_keys=("queries",),
    )
    queries = [str(q).strip() for q in result.data["queries"] if str(q).strip()] \
        if isinstance(result.data["queries"], list) else []
    if not queries:
        raise PermanentError("planned no search queries", use_fallback=False)
    return queries[:QUERIES_PER_SCOUT]


async def web_search(job: ResearchJob, scout: str, query: str, primary: str, fallback: str | None) -> list[SearchHit]:
    """Search with retries; if the primary provider fails, try the fallback. Returns [] if both fail."""
    for provider in [primary] + ([fallback] if fallback else []):
        def on_retry(error, attempt, delay, provider=provider):
            job.bus.log(f"{error.message} - retry {attempt} of {job.policy.max_retries} in {delay:.0f}s",
                        "warning", job.stage, scout)
        try:
            hits = await with_retries(lambda p=provider: job.search.search(p, query, RESULTS_PER_QUERY),
                                      job.policy, job.sleep, on_retry)
        except LLMError as error:
            job.bus.log(f"{SEARCH_PROVIDERS[provider].label} search failed: {error.message}", "warning",
                        job.stage, scout)
            continue
        record_search_cost(job, scout, provider, sum(hit.cost_usd for hit in hits))
        return hits
    return []


async def read_pages(job: ResearchJob, sources: list[Source]) -> None:
    """Replace snippets with the real page text where the page can be read."""
    to_read = [s for s in sources if not s.full_text][:PAGES_TO_READ]
    texts = await asyncio.gather(*(job.search.fetch_text(s.url) for s in to_read))
    for source, text in zip(to_read, texts):
        if text and not source.full_text:
            source.text, source.full_text = text, True


async def write_notes(job: ResearchJob, scout: str, angle: str, sources: list[Source]) -> str:
    prompt = prompts.render("scout_notes", scout=scout, angle=angle, book_summary=book_summary(job.profile),
                            sources=research_texts_for_prompt(sources))
    result = await job.gateway.chat(
        agent=scout, stage=job.stage, model=job.models.model_for(scout), fallback_model=job.models.fallback,
        messages=[{"role": "user", "content": prompt}], max_tokens=NOTES_MAX_TOKENS, thinking="off",
    )
    if "[S" not in result.text:
        job.bus.log("Notes contain no source citations - treat them with care", "warning", job.stage, scout)
    return result.text.strip()


def record_search_cost(job: ResearchJob, scout: str, provider: str, cost_usd: float) -> None:
    """Log every web search in costs.jsonl (searches can cost money too), and charge any known cost."""
    job.gateway.budget.add(cost_usd)
    job.bus.set_cost(job.gateway.budget.spent_usd, job.gateway.budget.limit_usd)
    tag = {"item": job.gateway.cost_tag} if job.gateway.cost_tag else {}
    storage.append_cost(job.book, {"stage": job.stage, "agent": scout, "model": f"search:{provider}",
                                   "input_tokens": 0, "output_tokens": 0, "cost_usd": cost_usd, "ok": True, **tag})


def book_summary(profile: BookProfile) -> str:
    return (f"'{profile.working_title}' - {profile.subject} Audience: {profile.audience} "
            f"(age {profile.audience_age}). Must include: {'; '.join(profile.must_include) or 'n/a'}.")


# ---------- the research brief (research/topic.md) ----------

def write_topic_brief(book: Book, profile: BookProfile) -> str:
    """(Re)build research/topic.md from the Scouts' notes, leaving out excluded sources."""
    sources = load_sources(book)
    excluded = {s.id for s in sources if s.excluded}
    used = [s for s in sources if not s.excluded]
    high = sum(1 for s in used if s.quality >= HIGH_QUALITY)

    parts = [f"# Research brief: {profile.working_title or book.title}",
             f"_{date.today().isoformat()} · {len(used)} sources ({high} high quality)"
             f"{f' · {len(excluded)} excluded by you' if excluded else ''}_"]
    for scout, angle in SCOUT_ANGLES.items():
        notes_path = book.folder / f"research/notes-{scout.lower()}.md"
        if notes_path.exists():
            notes = remove_excluded_citations(notes_path.read_text(encoding="utf-8"), excluded)
            parts.append(f"## {scout}: {angle.split(' - ')[0].capitalize()}\n\n{notes}")
    parts.append("## Sources\n\n" + source_list_markdown(sources))

    text = "\n\n".join(parts) + "\n"
    (book.folder / TOPIC_FILE).write_text(text, encoding="utf-8")
    return text


def read_topic_brief(book: Book) -> str:
    path = book.folder / TOPIC_FILE
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ---------- provider comparison (Developer menu) ----------

async def compare_providers(search: SearchClient, query: str) -> list[dict]:
    """Run one query on every provider that has a key, plus the scholarly sources. No AI calls."""
    async def measure(name: str, call) -> dict:
        start = time.monotonic()
        try:
            hits = await call()
        except LLMError as error:
            return {"provider": name, "error": error.message}
        scores = [score_source(h.url, h.scholarly)[0] for h in hits]
        return {"provider": name, "results": len(hits), "full_text": sum(h.full_text for h in hits),
                "avg_quality": round(sum(scores) / len(scores)) if scores else 0,
                "seconds": round(time.monotonic() - start, 1)}

    rows = [await measure(SEARCH_PROVIDERS[p].label, lambda p=p: search.search(p, query, RESULTS_PER_QUERY))
            for p in SEARCH_PROVIDERS if search.has_key(p)]
    rows.append(await measure("Scholarly (Wikipedia+OpenAlex+Crossref)", lambda: search.scholarly_search(query)))
    return rows
