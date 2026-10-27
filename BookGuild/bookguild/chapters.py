"""Chapter records and files (inside the book's workspace - see storage.py).

    chapters.json              one ChapterRecord per outline chapter (status, words, flags…)
    chapters/NN/research.md    the chapter Scout's cited notes
    chapters/NN/evidence.json  the source ids the Scribes were given
    chapters/NN/drafts.json    every Scribe's draft (with [S#] source markers)
    chapters/NN/jury.json      the Council's verdict on the drafts
    chapters/NN/revised.md     the winner after the Chair's note
    chapters/NN/factcheck.json the Archivist's findings (first check, and the re-check after a fix)
    chapters/NN/final.md       the chapter, still with [S#] markers (the export strips them)

Drafts keep source markers like [S17] after factual sentences so the jury and the Archivist can
check them; `strip_markers` removes them for reading and for the printed book.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from bookguild import storage
from bookguild.events import Status
from bookguild.outline import Outline
from bookguild.storage import Book

CHAPTERS_FILE = "chapters.json"
MARKERS = re.compile(r"\s*\[(?:S\d+|NEEDS SOURCE)\](?:\[S\d+\])*")


@dataclass
class ChapterRecord:
    number: int  # 1-based, follows the outline
    title: str
    status: str = Status.IDLE  # idle / running / done / failed
    step: str = ""  # what is happening now, e.g. "drafting", "fact-checking"
    words: int = 0
    flags: int = 0  # critical/major problems the Archivist still sees in the final text
    winner: str = ""  # which Scribe's draft won, e.g. "Scribe-2"
    error: str = ""


def load_records(book: Book, outline: Outline) -> list[ChapterRecord]:
    """One record per outline chapter. Saved records are matched by number; a renamed chapter keeps its record."""
    path = book.folder / CHAPTERS_FILE
    saved = {r["number"]: ChapterRecord(**r) for r in json.loads(path.read_text(encoding="utf-8"))} \
        if path.exists() else {}
    records = []
    for number, plan in enumerate(outline.chapters, start=1):
        record = saved.get(number) or ChapterRecord(number=number, title=plan.title)
        record.title = plan.title
        if record.status == Status.RUNNING:  # the app was closed mid-chapter: it needs another go
            record.status, record.step = Status.FAILED, "interrupted"
        records.append(record)
    return records


def save_records(book: Book, records: list[ChapterRecord]) -> None:
    path = book.folder / CHAPTERS_FILE
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps([asdict(r) for r in records], indent=1, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def chapters_folder(book: Book) -> Path:
    return book.folder / "chapters"


def chapter_dir(book: Book, number: int) -> Path:
    folder = chapters_folder(book) / f"{number:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def read_file(book: Book, number: int, name: str) -> str:
    path = chapters_folder(book) / f"{number:02d}" / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_file(book: Book, number: int, name: str, text: str) -> None:
    (chapter_dir(book, number) / name).write_text(text, encoding="utf-8")


def read_json(book: Book, number: int, name: str):
    text = read_file(book, number, name)
    return json.loads(text) if text else None


def write_json(book: Book, number: int, name: str, data) -> None:
    write_file(book, number, name, json.dumps(data, indent=1, ensure_ascii=False))


def strip_markers(text: str) -> str:
    """Remove [S17] / [NEEDS SOURCE] markers for reading and printing."""
    return MARKERS.sub("", text)


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’-]+", strip_markers(text)))


def cost_tag(book: Book, number: int) -> str:
    """The `item` tag in costs.jsonl for a chapter's calls (so per-chapter costs add up even when
    two chapters are written at once)."""
    return f"ch{number:02d}"


def chapter_cost(book: Book, number: int) -> float:
    tag = cost_tag(book, number)
    return sum(float(c.get("cost_usd", 0)) for c in storage.read_costs(book) if c.get("item") == tag)
