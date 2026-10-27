"""Image slots, candidates, the licence manifest and print-quality checks.

    images/manifest.json             every slot with its candidates and your decisions
    images/candidates/<slot>/<id>.*  previews of candidates (small)
    images/approved/<slot>.*         the chosen image at print size - only these go into the book
    images/credits.md                licence credits for the book's credits page

A slot is a place in a chapter that wants an image ("Homi Bhabha as a young man"). The Curator
plans slots; candidates come from licensed sources, AI or your own upload; you approve one or
skip the slot. Your uploads are approved straight away and recorded as "user-provided".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from bookguild.profile import BookProfile
from bookguild.storage import Book

MANIFEST_FILE = "images/manifest.json"
CREDITS_FILE = "images/credits.md"
TEXT_MARGINS_IN = 1.25  # trim width minus this ≈ printed text width (KDP inside + outside margins)
GOOD_DPI, MIN_DPI = 300, 200

SLOT_NEEDS_CHOICE, SLOT_APPROVED, SLOT_SKIPPED = "needs choice", "approved", "skipped"
NEW, APPROVED, REJECTED = "new", "approved", "rejected"


@dataclass
class Candidate:
    id: str  # "c1", "c2"…
    provider: str  # commons / pexels / pixabay / ai / upload
    title: str
    preview: str  # file path relative to the book folder
    full_url: str = ""  # where the print-size file is downloaded from on approval ("" for AI / uploads)
    page_url: str = ""  # the source page, for checking the licence yourself
    author: str = ""
    license: str = ""
    license_url: str = ""
    width: int = 0  # pixels of the print-size file
    height: int = 0
    ai_model: str = ""
    prompt: str = ""
    status: str = NEW  # new / approved / rejected
    found_by: str = ""  # the search words that found it (licensed images)


@dataclass
class ImageSlot:
    id: str  # "ch01-1"
    chapter: int
    purpose: str  # what the image should show
    caption: str = ""
    anchor: str = ""  # short quote from the chapter the image belongs next to
    source: str = "licensed"  # "licensed" or "ai" - the Curator's plan
    search_query: str = ""  # older books: a single search; new plans use search_queries
    role: str = "section"  # "chapter" = the chapter-opener image, "section" = an image inside the chapter
    search_queries: list[str] = field(default_factory=list)  # specific → wider
    ai_prompt: str = ""
    real_subject: bool = False  # shows a real person/place/object → licensed images only
    status: str = SLOT_NEEDS_CHOICE
    chosen: str = ""  # candidate id
    file: str = ""  # approved print file, relative to the book folder
    candidates: list[Candidate] = field(default_factory=list)

    def candidate(self, candidate_id: str) -> Candidate | None:
        return next((c for c in self.candidates if c.id == candidate_id), None)

    def next_candidate_id(self) -> str:
        return f"c{len(self.candidates) + 1}"

    def queries(self) -> list[str]:
        return self.search_queries or ([self.search_query] if self.search_query else [self.purpose[:60]])


def load_slots(book: Book) -> list[ImageSlot]:
    path = book.folder / MANIFEST_FILE
    if not path.exists():
        return []
    slots = []
    for raw in json.loads(path.read_text(encoding="utf-8")):
        candidates = [Candidate(**c) for c in raw.pop("candidates", [])]
        slots.append(ImageSlot(**raw, candidates=candidates))
    return slots


def save_slots(book: Book, slots: list[ImageSlot]) -> None:
    path = book.folder / MANIFEST_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps([asdict(s) for s in slots], indent=1, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)
    (book.folder / CREDITS_FILE).write_text(credits_markdown(slots), encoding="utf-8")


def print_width_inches(profile: BookProfile) -> float:
    trim_width = float(profile.trim_size.split("x")[0])
    return max(2.0, trim_width - TEXT_MARGINS_IN)


def print_dpi(candidate: Candidate, profile: BookProfile) -> int:
    """Resolution if the image is printed across the full text width."""
    return int(candidate.width / print_width_inches(profile)) if candidate.width else 0


def dpi_verdict(dpi: int) -> str:
    if dpi >= GOOD_DPI:
        return "good for print"
    if dpi >= MIN_DPI:
        return "ok if printed smaller than full width"
    return "too small for print" if dpi else "size unknown"


def credits_markdown(slots: list[ImageSlot]) -> str:
    lines = ["# Image credits", ""]
    for slot in slots:
        chosen = slot.candidate(slot.chosen) if slot.status == SLOT_APPROVED else None
        if chosen is None:
            continue
        if chosen.provider == "ai":
            credit = f"AI-generated illustration ({chosen.ai_model})."
        elif chosen.provider == "upload":
            credit = "Provided by the author."
        else:
            licence = f"[{chosen.license}]({chosen.license_url})" if chosen.license_url else chosen.license
            credit = f"\"{chosen.title}\" by {chosen.author or 'unknown'}, {licence}, via {chosen.provider}" + \
                (f" ({chosen.page_url})" if chosen.page_url else "") + "."
        lines.append(f"- Chapter {slot.chapter}, {slot.caption or slot.purpose}: {credit}")
    return "\n".join(lines) + "\n"
