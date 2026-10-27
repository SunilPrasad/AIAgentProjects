"""Book folders on disk, with one WORKSPACE per model profile.

Each book has a folder under the books directory. Everything the AI creates lives in a
workspace named after the model profile (test / balanced / quality), so switching the
profile switches the whole book's work and nothing made with one profile shows in another:

    <books_dir>/<book-slug>/
        state.json                 the book's title and creation date (shared)
        brief.md                   your original idea / prompt (shared)
        style/                     your visual style samples (shared - your own input)
        workspaces/<profile>/
            state.json             stage progress, cost so far, budget
            log.jsonl              one JSON log entry per line
            costs.jsonl            one line per paid AI call (agent, model, tokens, $)
            profile.json, research/, outline.json, chapters/, images/, cover/ …

`Book.folder` is the open workspace (where stages read and write); `Book.root` is the book
folder. Books from before workspaces had everything in the book folder - `open_book` moves
that work into a workspace the first time the book is opened. Nothing is deleted.
Everything is plain files so you can open and read them yourself.
"""

from __future__ import annotations

import json
import re
import shutil
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
WORKSPACES_DIR = "workspaces"
SHARED = (BRIEF_FILE, STATE_FILE, "style", WORKSPACES_DIR)  # what stays in the book folder itself
DEFAULT_WORKSPACE = "test"
DEFAULT_BUDGET_USD = 5.0


@dataclass
class Book:
    folder: Path  # the open workspace: <root>/workspaces/<workspace>
    title: str
    created: str
    stages: dict[str, str] = field(default_factory=lambda: {s: Status.IDLE for s in STAGES})
    spent_usd: float = 0.0
    budget_usd: float = DEFAULT_BUDGET_USD
    root: Path | None = None  # the book folder (shared title, brief and style samples)
    workspace: str = DEFAULT_WORKSPACE  # the model profile this workspace belongs to

    def __post_init__(self) -> None:
        if self.root is None:
            self.root = self.folder


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].strip("-") or "book"


def provisional_title(brief: str, max_length: int = 60) -> str:
    """A working name taken from the first line of the brief, until the Architects propose a real title."""
    first_line = next((line.strip() for line in brief.splitlines() if line.strip()), "")
    if len(first_line) <= max_length:
        return first_line
    return first_line[:max_length].rsplit(" ", 1)[0] + "…"


def create_book(books_dir: Path, brief: str, title: str = "", workspace: str = DEFAULT_WORKSPACE) -> Book:
    """Create a book folder from your brief. The title is optional - a working name is taken from the brief."""
    brief = brief.strip()
    if not brief:
        raise ValueError("A book needs a brief describing your idea.")
    title = title.strip() or provisional_title(brief)

    books_dir.mkdir(parents=True, exist_ok=True)
    root = books_dir / slugify(title)
    suffix = 2
    while root.exists():
        root = books_dir / f"{slugify(title)}-{suffix}"
        suffix += 1

    root.mkdir()
    _write_json(root / STATE_FILE, {"title": title, "created": datetime.now().isoformat(timespec="seconds")})
    (root / BRIEF_FILE).write_text(brief + "\n", encoding="utf-8")
    book = open_book(root, workspace)
    save_book(book)
    return book


def read_brief(book: Book) -> str:
    path = book.root / BRIEF_FILE
    return path.read_text(encoding="utf-8") if path.exists() else ""


def save_brief(book: Book, brief: str) -> None:
    (book.root / BRIEF_FILE).write_text(brief.strip() + "\n", encoding="utf-8")


def open_book(root: Path, workspace: str = DEFAULT_WORKSPACE, create: bool = True) -> Book:
    """The book in `root`, with the workspace of the given model profile open.
    `create=False` reads without making the workspace folder (for listing books)."""
    shared = json.loads((root / STATE_FILE).read_text(encoding="utf-8"))
    migrate_to_workspaces(root, shared)
    folder = root / WORKSPACES_DIR / workspace
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / STATE_FILE
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    stages = {s: Status.IDLE for s in STAGES}
    stages.update(state.get("stages", {}))
    return Book(
        folder=folder,
        title=shared["title"],
        created=shared.get("created", ""),
        stages=stages,
        spent_usd=float(state.get("spent_usd", 0.0)),
        budget_usd=float(state.get("budget_usd", DEFAULT_BUDGET_USD)),
        root=root,
        workspace=workspace,
    )


def list_books(books_dir: Path, workspace: str = DEFAULT_WORKSPACE) -> list[Book]:
    """All books in the books directory (with that workspace's progress), newest first.
    Unreadable folders are skipped."""
    if not books_dir.exists():
        return []

    books = []
    for root in books_dir.iterdir():
        if not (root / STATE_FILE).is_file():
            continue
        try:
            books.append(open_book(root, workspace, create=False))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(books, key=lambda b: b.created, reverse=True)


def save_book(book: Book) -> None:
    """Write the workspace's state.json and the shared title, atomically (a crash never leaves
    a half-written file)."""
    book.folder.mkdir(parents=True, exist_ok=True)
    _write_json(book.folder / STATE_FILE, {"stages": book.stages, "spent_usd": book.spent_usd,
                                           "budget_usd": book.budget_usd})
    shared_path = book.root / STATE_FILE
    shared = json.loads(shared_path.read_text(encoding="utf-8")) if shared_path.exists() else {}
    if shared.get("title") != book.title or "created" not in shared:
        _write_json(shared_path, {"title": book.title, "created": shared.get("created", book.created)})


def migrate_to_workspaces(root: Path, shared: dict) -> str | None:
    """Move a book from before workspaces into workspaces/<profile>/. Returns the workspace it
    went to, or None if there was nothing to move. Nothing is deleted.

    The profile is the book's old `chapter_set` (if any), else "test" - the profile everything
    was made with before workspaces existed.
    """
    legacy = [p for p in root.iterdir() if p.name not in SHARED and not p.name.endswith(".tmp")]
    old_stage_fields = {k: shared[k] for k in ("stages", "spent_usd", "budget_usd") if k in shared}
    if not legacy and not old_stage_fields:
        return None
    workspace = shared.get("chapter_set") or DEFAULT_WORKSPACE
    target = root / WORKSPACES_DIR / workspace
    target.mkdir(parents=True, exist_ok=True)
    for item in legacy:
        if not (target / item.name).exists():
            shutil.move(str(item), str(target / item.name))
    _flatten_chapter_sets(root, target, workspace)
    if old_stage_fields and not (target / STATE_FILE).exists():
        _write_json(target / STATE_FILE, old_stage_fields)
    _write_json(root / STATE_FILE, {"title": shared["title"], "created": shared.get("created", "")})
    return workspace


def _flatten_chapter_sets(root: Path, target: Path, workspace: str) -> None:
    """Chapters briefly lived in chapters/<set>/ (before workspaces): put each set's chapters
    into its own workspace as chapters/NN/, and drop the set prefix from cost tags."""
    chapters = target / "chapters"
    if not chapters.exists():
        return
    for set_folder in [p for p in chapters.iterdir() if p.is_dir() and not p.name.isdigit()]:
        destination = chapters if set_folder.name == workspace else \
            root / WORKSPACES_DIR / set_folder.name / "chapters"
        destination.mkdir(parents=True, exist_ok=True)
        for item in set_folder.iterdir():
            if not (destination / item.name).exists():
                shutil.move(str(item), str(destination / item.name))
        if not any(set_folder.iterdir()):
            set_folder.rmdir()
    costs = target / COSTS_FILE
    if costs.exists():
        records = [json.loads(line) for line in costs.read_text(encoding="utf-8").splitlines() if line.strip()]
        for record in records:
            if ":" in str(record.get("item", "")):
                record["item"] = record["item"].split(":", 1)[1]
        costs.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _write_json(path: Path, data: dict) -> None:
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp_path.replace(path)


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
