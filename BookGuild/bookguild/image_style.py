"""Book-wide style samples. They are your own input, so they live in the book folder and are
shared by every workspace (storage.py), independently of AI-generated profiles."""

from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader

from bookguild.reliability import PermanentError
from bookguild.storage import Book

MANIFEST = "style/references.json"
MAX_REFERENCES = 3
REFERENCE_GUIDANCE = (
    "Use the attached images as the visual style guide for this entire book: match their palette, "
    "lighting, texture, linework, rendering and level of realism consistently. "
    "Illustrate the requested new subject; do not copy the samples' subjects, composition, text or logos. "
    "Apply the written book-wide image instructions as well."
)


def load_references(book: Book) -> list[dict[str, str]]:
    path = book.root / MANIFEST
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _reference_path(book: Book, relative: str) -> Path:
    root = (book.root / "style/references").resolve()
    path = (book.root / relative).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != ".png":
        raise PermanentError("Invalid style reference path", use_fallback=False)
    return path


def _save(book: Book, references: list[dict[str, str]]) -> None:
    path = book.root / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(references, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def add_reference(book: Book, source: Path) -> None:
    references = load_references(book)
    if len(references) >= MAX_REFERENCES:
        raise PermanentError("Use up to 3 style samples per book. Remove one before adding another.",
                             use_fallback=False)
    reader = QImageReader(str(source))
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 40_000_000:
        raise PermanentError("Choose a readable image of at most 40 megapixels.", use_fallback=False)
    if max(size.width(), size.height()) > 1024:
        reader.setScaledSize(size.scaled(QSize(1024, 1024), Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    relative = f"style/references/{uuid.uuid4().hex}.png"
    path = _reference_path(book, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if image.isNull() or not image.save(str(path), "PNG"):
        raise PermanentError("Could not save the style sample. Choose another image.", use_fallback=False)
    references.append({"name": source.name, "file": relative})
    _save(book, references)


def remove_reference(book: Book, relative: str) -> None:
    references = load_references(book)
    if not any(r["file"] == relative for r in references):
        return
    _save(book, [r for r in references if r["file"] != relative])
    _reference_path(book, relative).unlink(missing_ok=True)


def reference_data_urls(book: Book) -> list[str]:
    urls = []
    for reference in load_references(book):
        path = _reference_path(book, reference["file"])
        if not path.is_file():
            raise PermanentError(f"Style sample '{reference['name']}' is missing. Re-add or remove it in Profile.",
                                 use_fallback=False)
        urls.append("data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii"))
    return urls
