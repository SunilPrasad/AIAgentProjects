"""Book folders on disk.

Each book lives in its own folder under the books directory:

    <books_dir>/<book-slug>/
        brief.md     your original idea / prompt for the book
        state.json   title, stage progress, cost so far
        log.jsonl    one JSON log entry per line
        costs.jsonl  one line per paid AI call (agent, model, tokens, $)

Later phases add profile.json, research/, chapters/, images/ and so on.
Everything is plain files so you can open and read them yourself.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from bookguild.events import LogEntry, Status

STAGES = ("profile", "research", "outline", "chapters", "images", "cover", "export")
STAGE_LABELS = {
    "profile": "Profile",
    "research": "Research",
    "outline": "Outline",
    "chapters": "Chapters",
    "images": "Images",
    "cover": "Cover",
    "export": "Export",
}

BRIEF_FILE = "brief.md"
STATE_FILE = "state.json"
LOG_FILE = "log.jsonl"
COSTS_FILE = "costs.jsonl"
DEFAULT_BUDGET_USD = 5.0


@dataclass
class Book:
    folder: Path
    title: str
    created: str
    stages: dict[str, str] = field(default_factory=lambda: {s: Status.IDLE for s in STAGES})
    spent_usd: float = 0.0
    budget_usd: float = DEFAULT_BUDGET_USD


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].strip("-") or "book"


def provisional_title(brief: str, max_length: int = 60) -> str:
    """A working name taken from the first line of the brief, until the Architects propose a real title."""
    first_line = next((line.strip() for line in brief.splitlines() if line.strip()), "")
    if len(first_line) <= max_length:
        return first_line
    return first_line[:max_length].rsplit(" ", 1)[0] + "…"


def create_book(books_dir: Path, brief: str, title: str = "") -> Book:
    """Create a book folder from your brief. The title is optional - a working name is taken from the brief."""
    brief = brief.strip()
    if not brief:
        raise ValueError("A book needs a brief describing your idea.")
    title = title.strip() or provisional_title(brief)

    books_dir.mkdir(parents=True, exist_ok=True)
    folder = books_dir / slugify(title)
    suffix = 2
    while folder.exists():
        folder = books_dir / f"{slugify(title)}-{suffix}"
        suffix += 1

    folder.mkdir()
    book = Book(folder=folder, title=title, created=datetime.now().isoformat(timespec="seconds"))
    save_book(book)
    save_brief(book, brief)
    return book


def read_brief(book: Book) -> str:
    path = book.folder / BRIEF_FILE
    return path.read_text(encoding="utf-8") if path.exists() else ""


def save_brief(book: Book, brief: str) -> None:
    (book.folder / BRIEF_FILE).write_text(brief.strip() + "\n", encoding="utf-8")


def open_book(folder: Path) -> Book:
    data = json.loads((folder / STATE_FILE).read_text(encoding="utf-8"))
    stages = {s: Status.IDLE for s in STAGES}
    stages.update(data.get("stages", {}))
    return Book(
        folder=folder,
        title=data["title"],
        created=data.get("created", ""),
        stages=stages,
        spent_usd=float(data.get("spent_usd", 0.0)),
        budget_usd=float(data.get("budget_usd", DEFAULT_BUDGET_USD)),
    )


def list_books(books_dir: Path) -> list[Book]:
    """All books in the books directory, newest first. Unreadable folders are skipped."""
    if not books_dir.exists():
        return []

    books = []
    for folder in books_dir.iterdir():
        if not (folder / STATE_FILE).is_file():
            continue
        try:
            books.append(open_book(folder))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(books, key=lambda b: b.created, reverse=True)


def save_book(book: Book) -> None:
    """Write state.json atomically, so a crash never leaves a half-written file."""
    data = asdict(book)
    data.pop("folder")
    temp_path = book.folder / (STATE_FILE + ".tmp")
    temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp_path.replace(book.folder / STATE_FILE)


def append_log(book: Book, entry: LogEntry) -> None:
    with open(book.folder / LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry)) + "\n")


def append_cost(book: Book, record: dict) -> None:
    """One line per paid AI call: stage, agent, model, tokens, cost."""
    record = {"time": datetime.now().isoformat(timespec="seconds"), **record}
    with open(book.folder / COSTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def read_costs(book: Book) -> list[dict]:
    path = book.folder / COSTS_FILE
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def read_log(book: Book, limit: int = 1000) -> list[LogEntry]:
    """The last `limit` log entries. Corrupt lines are skipped."""
    path = book.folder / LOG_FILE
    if not path.exists():
        return []

    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(LogEntry(**json.loads(line)))
        except (ValueError, TypeError):
            continue
    return entries[-limit:]
