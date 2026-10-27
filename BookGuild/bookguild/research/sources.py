"""The book's numbered source list (research/sources.json) and source quality scoring.

Every source gets a stable id (S1, S2, …) that the Scouts' notes cite, e.g. "Raman won the
Nobel Prize in 1930 [S4]". You can exclude a source; excluded sources are left out of the
research brief and are never given to later agents.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from urllib.parse import urlsplit

from bookguild.config import PROJECT_ROOT
from bookguild.research.search import SearchHit
from bookguild.storage import Book

QUALITY_CONFIG_PATH = PROJECT_ROOT / "config" / "source_quality.toml"
SOURCES_FILE = "research/sources.json"
HIGH_QUALITY = 70  # score at or above this counts as "high quality" in summaries


@dataclass
class Source:
    id: str  # "S1", "S2", …
    url: str
    title: str
    domain: str
    provider: str  # which search found it first
    text: str  # page text or snippet given to the Scouts
    quality: int
    quality_note: str
    full_text: bool = False
    found_by: list[str] = field(default_factory=list)  # Scout names
    queries: list[str] = field(default_factory=list)
    excluded: bool = False


class SourceRegistry:
    """Collects hits from all Scouts, removes duplicates and blocked sites, and numbers them."""

    def __init__(self, sources: list[Source] | None = None):
        self.sources: dict[str, Source] = {}  # normalised url -> Source
        for source in sources or []:
            self.sources[normalise_url(source.url)] = source

    def add(self, hit: SearchHit, scout: str, query: str) -> Source | None:
        """Add a hit (or merge it into the same URL found earlier). Returns None for blocked sites."""
        key = normalise_url(hit.url)
        title = " ".join(hit.title.split())  # some sites put line breaks in titles
        existing = self.sources.get(key) or self._same_page(hit.url, title)
        if existing is None:
            quality, note = score_source(hit.url, hit.scholarly)
            if quality <= 0:
                return None
            existing = Source(id=f"S{len(self.sources) + 1}", url=hit.url, title=title or hit.url,
                              domain=domain_of(hit.url), provider=hit.provider, text=hit.text,
                              quality=quality, quality_note=note, full_text=hit.full_text)
            self.sources[key] = existing
        elif hit.full_text and not existing.full_text:  # keep the richer copy of the text
            existing.text, existing.full_text = hit.text, True
        if scout not in existing.found_by:
            existing.found_by.append(scout)
        if query not in existing.queries:
            existing.queries.append(query)
        return existing

    def _same_page(self, url: str, title: str) -> Source | None:
        """The same page under a slightly different URL (e.g. Wikipedia's C._V._Raman vs C.V._Raman)."""
        domain = domain_of(url)
        return next((s for s in self.sources.values()
                     if title and s.domain == domain and s.title.lower() == title.lower()), None)

    def all(self) -> list[Source]:
        return sorted(self.sources.values(), key=lambda s: int(s.id[1:]))


def load_sources(book: Book) -> list[Source]:
    path = book.folder / SOURCES_FILE
    if not path.exists():
        return []
    return [Source(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def save_sources(book: Book, sources: list[Source]) -> None:
    path = book.folder / SOURCES_FILE
    path.parent.mkdir(exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps([asdict(s) for s in sources], indent=1, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


# ---------- quality scoring ----------

@lru_cache(maxsize=1)
def _quality_config() -> dict:
    with open(QUALITY_CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def score_source(url: str, scholarly: bool = False) -> tuple[int, str]:
    """(score 0-100, reason). Score 0 means blocked."""
    config = _quality_config()
    scores, lists = config["scores"], config["domains"]
    domain = domain_of(url)

    if _matches(domain, lists["blocked"]):
        return 0, "blocked site"
    if scholarly:
        return scores["scholarly"], "scholarly paper"
    if re.search(r"\.(gov|edu|mil)(\.[a-z]{2})?$|\.ac\.[a-z]{2}$|\.nic\.in$|\.res\.in$", domain):
        return scores["gov_edu"], "government / university"
    if _matches(domain, lists["trusted"]):
        return scores["trusted"], "trusted publisher"
    if domain.endswith("wikipedia.org"):
        return scores["wikipedia"], "Wikipedia"
    if _matches(domain, lists["low"]):
        return scores["low"], "user-generated or low-quality site"
    return scores["default"], "unrated site"


def _matches(domain: str, entries: list[str]) -> bool:
    return any(domain == entry or domain.endswith("." + entry) for entry in entries)


def domain_of(url: str) -> str:
    host = urlsplit(url).netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def normalise_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return f"{domain_of(url)}{parts.path.rstrip('/')}".lower()


# ---------- the research brief ----------

CITATION = re.compile(r"\[(S\d+)\]")


def remove_excluded_citations(notes: str, excluded_ids: set[str]) -> str:
    """Drop note lines that are supported ONLY by excluded sources; strip excluded ids from the rest."""
    kept = []
    for line in notes.splitlines():
        cited = set(CITATION.findall(line))
        if cited and cited <= excluded_ids:
            continue
        for source_id in cited & excluded_ids:
            line = line.replace(f"[{source_id}]", "")
        kept.append(line.rstrip())
    return "\n".join(kept)


def source_list_markdown(sources: list[Source]) -> str:
    lines = []
    for s in sources:
        if s.excluded:
            continue
        lines.append(f"- **[{s.id}]** [{s.title}]({s.url}) - {s.domain} · quality {s.quality} ({s.quality_note})")
    return "\n".join(lines)


def research_texts_for_prompt(sources: list[Source], ids: list[str] | None = None, max_chars: int = 3500) -> str:
    """Numbered source texts for a prompt. Excluded sources are never included."""
    chosen = [s for s in sources if not s.excluded and (ids is None or s.id in ids)]
    return "\n\n".join(f"[{s.id}] {s.title} ({s.domain})\n{s.text[:max_chars]}" for s in chosen)

