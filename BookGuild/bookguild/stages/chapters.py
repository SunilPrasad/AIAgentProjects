"""Stage 4 - Chapters: research, draft, judge, revise and fact-check each chapter.

For each chapter:
  1. research      a Scout researches this chapter's subject (adds to the book's numbered sources)
  2. drafting      every Scribe (different providers) writes a full draft, citing sources as [S17]
  3. judging       the Council picks the best draft blind (accuracy weighs most)
  4. revising      the winning Scribe applies the Chair's note - exactly once
  5. fact-checking the Archivist checks every claim against the evidence; if critical/major
                   problems are found, ONE fix pass and ONE re-check, then whatever is still
                   flagged is shown to you

Hard limits keep this from looping: one revision, one fix pass, one re-check.

Each step is saved before the next starts (see chapters.py), so retrying a failed chapter
resumes where it stopped instead of paying again for finished work. Up to
CHAPTERS_IN_PARALLEL chapters run at once; one chapter failing never stops the others, but
a spent budget or a paused pipeline stops the remaining chapters.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass
from typing import Awaitable, Callable

from bookguild import prompts, storage
from bookguild.chapters import (
    ChapterRecord,
    read_file,
    read_json,
    word_count,
    write_file,
    write_json,
)
from bookguild.events import EventBus, Status
from bookguild.gateway import AIGateway
from bookguild.jury import Criterion, judge
from bookguild.models import ModelProfile
from bookguild.outline import ChapterPlan, Outline
from bookguild.profile import BookProfile
from bookguild.reliability import BudgetExceeded, Failure, LLMError, PermanentError, PipelinePaused, TransientError
from bookguild.research.search import SearchClient
from bookguild.research.sources import SourceRegistry, research_texts_for_prompt, save_sources
from bookguild.stages import research as research_stage
from bookguild.storage import Book

CHAPTERS_IN_PARALLEL = 2
MAX_SCRIBES = 5
MIN_DRAFTS = 2
EVIDENCE_SOURCES = 14  # best sources given to the Scribes for one chapter
EVIDENCE_CHARS_PER_SOURCE = 3000
JURY_EVIDENCE_CHARS = 25_000
BLOCKING = ("critical", "major")
NEEDS_SOURCE = "[NEEDS SOURCE]"


@dataclass
class ChapterJob:
    book: Book
    profile: BookProfile
    outline: Outline
    models: ModelProfile
    search: SearchClient
    bus: EventBus
    registry: SourceRegistry  # the book's numbered sources, shared by chapters running at the same time
    make_gateway: Callable[..., AIGateway]  # make_gateway(step_retry=..., cost_tag=...)
    retry_chapter: Callable[[int], Awaitable]  # what the Failures panel's Retry runs
    on_update: Callable[[ChapterRecord], None]  # save the record and refresh the UI


def scribe_names(models: ModelProfile) -> list[str]:
    return [f"Scribe-{i + 1}" for i in range(min(MAX_SCRIBES, len(models.scribes)))]


def chapter_rubric(profile: BookProfile) -> list[Criterion]:
    return [
        Criterion("accuracy", "Every factual sentence is supported by the evidence it cites; no invented dialogue, "
                              "quotes, thoughts, scenes or 'firsts'; no guesses marked [NEEDS SOURCE]; legends are "
                              "not presented as fact.", 3 if profile.mode == "evidence" else 1),
        Criterion("brief", "Follows the author's brief and style notes, and covers the chapter plan's key points.", 2),
        Criterion("audience", f"Right for readers aged {profile.audience_age} ('{profile.reading_level}'): "
                              "familiar words, short sentences, one idea per paragraph.", 2),
        Criterion("engagement", "Vivid, story-like and warm, with a documented opening, a clear arc and a strong "
                                "ending - without padding or hero-worship.", 2),
        Criterion("clarity", "Ideas are explained with everyday examples; no repetition or digressions.", 1),
    ]


# ---------- running chapters ----------

async def run(job: ChapterJob, numbers: list[int], instruction: str = "") -> list[ChapterRecord]:
    """Write the given chapters, up to CHAPTERS_IN_PARALLEL at a time."""
    gate = asyncio.Semaphore(CHAPTERS_IN_PARALLEL)
    stopped = False

    async def one(number: int) -> ChapterRecord | None:
        nonlocal stopped
        async with gate:
            if stopped:
                return None
            try:
                return await write_chapter(job, number, instruction)
            except (BudgetExceeded, PipelinePaused):
                stopped = True  # no point starting more chapters
                return None

    results = await asyncio.gather(*(one(n) for n in numbers))
    return [r for r in results if r is not None]


def clear_chapter(book: Book, number: int) -> None:
    """Forget all saved work for a chapter, so it is written from scratch."""
    shutil.rmtree(book.folder / "chapters" / f"{number:02d}", ignore_errors=True)


async def write_chapter(job: ChapterJob, number: int, instruction: str = "") -> ChapterRecord:
    plan = job.outline.chapters[number - 1]
    record = ChapterRecord(number=number, title=plan.title, status=Status.RUNNING)
    gateway = job.make_gateway(step_retry=lambda: job.retry_chapter(number), cost_tag=f"ch{number:02d}")

    def step(name: str) -> None:
        record.step = name
        job.on_update(record)
        job.bus.log(f"Chapter {number}: {name}…", stage="chapters", agent="Steward")

    try:
        step("researching")
        evidence = await chapter_evidence(job, gateway, number, plan)

        jury = read_json(job.book, number, "jury.json")
        if jury is None or instruction:
            step("drafting")
            drafts = await write_drafts(job, gateway, number, plan, evidence, instruction)
            step("judging")
            verdict = await judge(gateway, job.models, "chapters", task=task_text(job, number, plan),
                                  context=jury_context(job, plan, evidence),
                                  candidates=[d["text"] for d in drafts], rubric=chapter_rubric(job.profile))
            jury = {**verdict.to_dict(), "scribes": [d["scribe"] for d in drafts]}
            write_json(job.book, number, "drafts.json", drafts)
            write_json(job.book, number, "jury.json", jury)
            write_file(job.book, number, "revised.md", "")  # a new winner needs a new revision
        drafts = read_json(job.book, number, "drafts.json")
        winner = drafts[jury["winner"]]
        record.winner = winner["scribe"]

        text = read_file(job.book, number, "revised.md")
        if not text:
            text = winner["text"]
            if jury.get("chair_note"):
                step("revising")
                text = await revise_text(job, gateway, winner["scribe"], text, evidence,
                                         "Apply the Council Chair's improvement note:\n" + jury["chair_note"])
            write_file(job.book, number, "revised.md", text)

        text, flags = await fact_check(job, gateway, number, winner["scribe"], text, evidence, step)
        write_file(job.book, number, "final.md", text)
        record.status, record.step = Status.DONE, ""
        record.words, record.flags = word_count(text), flags
        job.bus.log(f"Chapter {number} done: {record.words} words, winner {record.winner}"
                    + (f", {flags} fact-check flag(s) left for you" if flags else ", fact-check clean"),
                    "success" if not flags else "warning", "chapters", "Archivist")
    except LLMError as error:
        record.status, record.error = Status.FAILED, error.message
        record.step = f"failed while {record.step}"
        if error.status is None and error.attempts == 0:  # not already reported by the gateway
            job.bus.log(f"Chapter {number} FAILED: {error.message}", "error", "chapters", "Steward")
            job.bus.failure_added.emit(Failure(stage="chapters", agent=f"Chapter {number}", model="-",
                                               error=error.message, kind="permanent", attempts=1,
                                               retry=lambda: job.retry_chapter(number)))
        if isinstance(error, (BudgetExceeded, PipelinePaused)):
            raise
    finally:
        job.on_update(record)
    return record


async def revise_chapter(job: ChapterJob, number: int, instruction: str, scribe: str) -> ChapterRecord:
    """Your change to a finished chapter: one revision by the winning Scribe, then the fact-check."""
    plan = job.outline.chapters[number - 1]
    record = ChapterRecord(number=number, title=plan.title, status=Status.RUNNING, winner=scribe)
    gateway = job.make_gateway(step_retry=None, cost_tag=f"ch{number:02d}")

    def step(name: str) -> None:
        record.step = name
        job.on_update(record)

    try:
        evidence = await chapter_evidence(job, gateway, number, plan)
        step("revising")
        text = await revise_text(job, gateway, scribe, read_file(job.book, number, "final.md"), evidence,
                                 f"The author asks: {instruction}")
        text, flags = await fact_check(job, gateway, number, scribe, text, evidence, step)
        write_file(job.book, number, "final.md", text)
        record.status, record.step, record.words, record.flags = Status.DONE, "", word_count(text), flags
    except LLMError as error:
        record.status, record.step, record.error = Status.DONE, "revision failed - kept the previous text", \
            error.message
    finally:
        job.on_update(record)
    return record


# ---------- steps ----------

async def chapter_evidence(job: ChapterJob, gateway: AIGateway, number: int, plan: ChapterPlan) -> str:
    """The numbered sources (and notes) the Scribes may use. Researched once per chapter, then reused."""
    ids = read_json(job.book, number, "evidence.json")
    if ids is None:
        ids, notes = await research_chapter(job, gateway, number, plan)
        write_json(job.book, number, "evidence.json", ids)
        write_file(job.book, number, "research.md", notes)
    notes = read_file(job.book, number, "research.md")
    sources = [s for s in job.registry.all() if s.id in ids and not s.excluded]
    sources = sorted(sources, key=lambda s: s.quality, reverse=True)[:EVIDENCE_SOURCES]
    if not sources:
        raise PermanentError("no usable sources for this chapter", use_fallback=False)
    texts = research_texts_for_prompt(sources, max_chars=EVIDENCE_CHARS_PER_SOURCE)
    return texts + (f"\n\nRESEARCH NOTES FOR THIS CHAPTER (cite the source ids, not the notes):\n{notes}"
                    if notes else "")


async def research_chapter(job: ChapterJob, gateway: AIGateway, number: int, plan: ChapterPlan):
    scout = f"Scout-{(number - 1) % 3 + 1}"
    angle = (f"everything a writer needs for chapter {number}, '{plan.title}': {plan.summary} "
             f"It must cover: {'; '.join(plan.key_points) or 'see the summary'}")
    research_job = research_stage.ResearchJob(job.book, job.profile, gateway, job.models, job.search, job.bus,
                                              stage="chapters")
    primary, fallback = research_stage.choose_providers(research_job)
    planned = [s.upper() for s in plan.sources]
    try:
        report = await research_stage.run_scout(research_job, scout, angle, job.registry, primary, fallback)
    except LLMError as error:
        if not planned:
            raise
        job.bus.log(f"Chapter {number} research failed ({error.message}) - using the outline's sources only",
                    "warning", "chapters", scout)
        return planned, ""
    save_sources(job.book, job.registry.all())
    ids = list(dict.fromkeys(planned + report.source_ids))  # planned sources first, no duplicates
    return ids, report.notes


async def write_drafts(job: ChapterJob, gateway: AIGateway, number: int, plan: ChapterPlan, evidence: str,
                       instruction: str) -> list[dict]:
    target = job.profile.words_per_chapter
    prompt_values = dict(profile=job.profile.for_prompt(), brief=storage.read_brief(job.book),
                         outline=job.outline.as_text(), number=str(number), title=plan.title, summary=plan.summary,
                         key_points="; ".join(plan.key_points) or "(see plan)", evidence=evidence,
                         words=str(target),
                         instruction=f"Extra instruction from the author: {instruction}" if instruction else "")

    async def draft(scribe: str) -> dict:
        prompt = prompts.render("scribe", scribe=scribe, **prompt_values)
        result = await gateway.chat(agent=scribe, stage="chapters", model=job.models.model_for(scribe),
                                    fallback_model=job.models.fallback, max_tokens=max(4000, target * 3),
                                    thinking="off", messages=[{"role": "user", "content": prompt}],
                                    validate=long_enough(target))
        return {"scribe": scribe, "model": result.model, "text": result.text.strip()}

    results = await asyncio.gather(*(draft(s) for s in scribe_names(job.models)), return_exceptions=True)
    drafts = [r for r in results if isinstance(r, dict)]
    for r in results:
        if isinstance(r, Exception) and not isinstance(r, LLMError):
            raise r  # a programming error - don't hide it
    if len(drafts) < min(MIN_DRAFTS, len(results)):
        raise PermanentError(f"only {len(drafts)} draft(s) - at least {MIN_DRAFTS} are needed for a vote",
                             use_fallback=False)
    return drafts


async def revise_text(job: ChapterJob, gateway: AIGateway, scribe: str, text: str, evidence: str,
                      instruction: str) -> str:
    profile = job.profile
    prompt = prompts.render("scribe_revise", scribe=scribe, book_summary=research_stage.book_summary(profile),
                            audience_age=profile.audience_age, reading_level=profile.reading_level,
                            tone=profile.tone, instruction=instruction, evidence=evidence, chapter=text,
                            words=str(profile.words_per_chapter))
    result = await gateway.chat(agent=scribe, stage="chapters", model=job.models.model_for(scribe),
                                fallback_model=job.models.fallback, thinking="off",
                                max_tokens=max(4000, profile.words_per_chapter * 3),
                                messages=[{"role": "user", "content": prompt}],
                                validate=long_enough(profile.words_per_chapter))
    return result.text.strip()


async def fact_check(job: ChapterJob, gateway: AIGateway, number: int, scribe: str, text: str, evidence: str,
                     step) -> tuple[str, int]:
    """Archivist check → (if needed) ONE surgical fix → ONE re-check. Returns (text, problems still flagged).

    The fix is surgical on purpose: rewriting the whole chapter to fix a few sentences made cheap
    models invent NEW details elsewhere (seen in testing). Now only the flagged sentences change.
    """
    text, removed = drop_unsourced_sentences(text)
    if removed:
        job.bus.log(f"Chapter {number}: removed {removed} sentence(s) marked [NEEDS SOURCE]", "warning",
                    "chapters", "Archivist")
    step("fact-checking")
    first = await archivist_check(job, gateway, text, evidence)
    report = {"first": first, "after_fix": None, "edits": []}
    problems = blocking(first)
    if problems:
        step(f"fixing {len(problems)} problem(s)")
        text, report["edits"] = await surgical_fix(job, gateway, scribe, text, evidence, problems)
        applied = sum(e["applied"] for e in report["edits"])
        job.bus.log(f"Chapter {number}: {applied} of {len(report['edits'])} fix(es) applied", stage="chapters",
                    agent=scribe)
        step("re-checking")
        report["after_fix"] = await archivist_check(job, gateway, text, evidence)
        problems = blocking(report["after_fix"])
    write_json(job.book, number, "factcheck.json", report)
    return text, len(problems)


async def surgical_fix(job: ChapterJob, gateway: AIGateway, scribe: str, text: str, evidence: str,
                       problems: list[dict]) -> tuple[str, list[dict]]:
    """Ask for exact find/replace edits of the flagged sentences and apply them in code."""
    findings = "\n".join(f"- [{f['severity']}] \"{f['quote']}\": {f['problem']} → {f['fix']}" for f in problems)
    prompt = prompts.render("scribe_fix", scribe=scribe, evidence=evidence, chapter=text, findings=findings)
    result = await gateway.chat_json(agent=scribe, stage="chapters", model=job.models.model_for(scribe),
                                     fallback_model=job.models.fallback, max_tokens=4000, thinking="off",
                                     messages=[{"role": "user", "content": prompt}], required_keys=("edits",))
    edits = []
    for edit in result.data["edits"] if isinstance(result.data["edits"], list) else []:
        if not isinstance(edit, dict) or not str(edit.get("find", "")).strip():
            continue
        find, replace = str(edit["find"]).strip(), str(edit.get("replace") or "").strip()
        applied = find in text
        if applied:
            text = text.replace(find, replace, 1)
        edits.append({"find": find, "replace": replace, "applied": applied})
    return tidy(text), edits


def drop_unsourced_sentences(text: str) -> tuple[str, int]:
    """Delete every sentence marked [NEEDS SOURCE] - done in code, so nothing new is invented."""
    removed = 0
    lines = []
    for line in text.splitlines():
        if NEEDS_SOURCE in line:
            sentences = re.split(r"(?<=[.!?])\s+", line)
            kept = [s for s in sentences if NEEDS_SOURCE not in s]
            removed += len(sentences) - len(kept)
            line = " ".join(kept)
        lines.append(line)
    return tidy("\n".join(lines)), removed


def tidy(text: str) -> str:
    """Clean up after deletions: double spaces and runs of blank lines."""
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def archivist_check(job: ChapterJob, gateway: AIGateway, text: str, evidence: str) -> dict:
    prompt = prompts.render("archivist", book_summary=research_stage.book_summary(job.profile), evidence=evidence,
                            chapter=text)
    result = await gateway.chat_json(agent="Archivist", stage="chapters", model=job.models.archivist,
                                     fallback_model=job.models.fallback, max_tokens=8000, thinking="off",
                                     messages=[{"role": "user", "content": prompt}],
                                     required_keys=("findings",), validate=_findings_list)
    findings = []
    for f in result.data["findings"]:
        if not isinstance(f, dict):
            continue
        severity = str(f.get("severity", "minor")).lower()
        findings.append({"quote": str(f.get("quote", "")), "severity": severity if severity in
                         ("critical", "major", "minor") else "minor", "problem": str(f.get("problem", "")),
                         "fix": str(f.get("fix", "")), "sources": f.get("sources") or []})
    return {"approved": not any(f["severity"] in BLOCKING for f in findings), "findings": findings,
            "summary": str(result.data.get("summary", ""))}


def blocking(check: dict) -> list[dict]:
    return [f for f in check["findings"] if f["severity"] in BLOCKING]


def long_enough(target_words: int):
    """A draft must reach at least 40% of the target length (else it's retried)."""
    def validate(text: str) -> None:
        if word_count(text) < 0.4 * target_words:
            raise TransientError(f"Chapter too short: {word_count(text)} words, target {target_words}")
    return validate


def task_text(job: ChapterJob, number: int, plan: ChapterPlan) -> str:
    return (f"Write chapter {number}, '{plan.title}', of '{job.outline.title}' for readers aged "
            f"{job.profile.audience_age}, about {job.profile.words_per_chapter} words. Plan: {plan.summary} "
            f"Key points: {'; '.join(plan.key_points)}")


def jury_context(job: ChapterJob, plan: ChapterPlan, evidence: str) -> str:
    return (f"Book Profile:\n{job.profile.for_prompt()}\n\nThe author's brief:\n{storage.read_brief(job.book)}\n\n"
            f"EVIDENCE the chapter must stick to (source ids like [S17]):\n{evidence[:JURY_EVIDENCE_CHARS]}")


def _findings_list(data) -> None:
    if not isinstance(data.get("findings"), list):
        raise TransientError("Archivist reply had no findings list")

