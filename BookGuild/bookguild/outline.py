"""The book's title and chapter outline.

Files in the book folder:
    outline/proposals.json   the Architects' proposals (which Architect, which model, the outline)
    outline/jury.json        the Council's verdict on them (votes, reasons, Chair's note)
    outline.json             the outline you are working on / approved (starts as the winner)

Like the Book Profile, `Outline.from_dict` never trusts model output.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from bookguild.storage import Book

OUTLINE_FILE = "outline.json"
PROPOSALS_FILE = "outline/proposals.json"
JURY_FILE = "outline/jury.json"
MAX_CHAPTERS = 60


@dataclass
class ChapterPlan:
    title: str
    summary: str = ""  # 2-3 sentences: what the chapter covers and how it opens
    key_points: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # research source ids, e.g. ["S4", "S17"]


@dataclass
class Outline:
    title: str
    subtitle: str = ""
    pitch: str = ""  # 1-2 sentences, back-cover style
    chapters: list[ChapterPlan] = field(default_factory=list)
    approved: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def as_text(self) -> str:
        """Plain text for prompts (jurors, Chair, later the Scribes)."""
        lines = [f"Title: {self.title}", f"Subtitle: {self.subtitle}", f"Pitch: {self.pitch}", "", "Chapters:"]
        for number, chapter in enumerate(self.chapters, start=1):
            lines.append(f"{number}. {chapter.title} - {chapter.summary}")
            lines += [f"   - {point}" for point in chapter.key_points]
            if chapter.sources:
                lines.append(f"   sources: {' '.join(chapter.sources)}")
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict) -> tuple[Outline, list[str]]:
        """Build a valid outline from untrusted data. Returns (outline, warnings)."""
        if not isinstance(data, dict):
            raise ValueError("Outline data was not an object")
        warnings = []
        chapters = []
        for raw in data.get("chapters") or []:
            if isinstance(raw, str):
                raw = {"title": raw}
            if not isinstance(raw, dict) or not str(raw.get("title", "")).strip():
                warnings.append("Skipped a chapter without a title.")
                continue
            chapters.append(ChapterPlan(
                title=_clean(raw.get("title")),
                summary=_clean(raw.get("summary")),
                key_points=_strings(raw.get("key_points")),
                sources=[s.upper() for s in _strings(raw.get("sources")) if s.upper().startswith("S")],
            ))
        if len(chapters) > MAX_CHAPTERS:
            warnings.append(f"Kept the first {MAX_CHAPTERS} of {len(chapters)} chapters.")
            chapters = chapters[:MAX_CHAPTERS]
        title = _clean(data.get("title"))
        if not title:
            warnings.append("The outline had no title.")
        return cls(title=title or "Untitled", subtitle=_clean(data.get("subtitle")), pitch=_clean(data.get("pitch")),
                   chapters=chapters, approved=bool(data.get("approved", False))), warnings


@dataclass
class Proposal:
    architect: str
    model: str
    outline: Outline


def load_outline(book: Book) -> Outline | None:
    path = book.folder / OUTLINE_FILE
    if not path.exists():
        return None
    outline, _ = Outline.from_dict(json.loads(path.read_text(encoding="utf-8")))
    return outline


def save_outline(book: Book, outline: Outline) -> None:
    _write_json(book, OUTLINE_FILE, outline.to_dict())


def load_proposals(book: Book) -> list[Proposal]:
    path = book.folder / PROPOSALS_FILE
    if not path.exists():
        return []
    return [Proposal(p["architect"], p["model"], Outline.from_dict(p["outline"])[0])
            for p in json.loads(path.read_text(encoding="utf-8"))]


def save_proposals(book: Book, proposals: list[Proposal]) -> None:
    _write_json(book, PROPOSALS_FILE, [{"architect": p.architect, "model": p.model, "outline": p.outline.to_dict()}
                                       for p in proposals])


def load_verdict(book: Book) -> dict | None:
    path = book.folder / JURY_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save_verdict(book: Book, verdict: dict) -> None:
    _write_json(book, JURY_FILE, verdict)


def _write_json(book: Book, relative: str, data) -> None:
    path = book.folder / relative
    path.parent.mkdir(exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _strings(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [_clean(v) for v in value if _clean(v)]
