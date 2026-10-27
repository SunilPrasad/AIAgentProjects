"""Stage 5 - Images: the Curator plans image slots and finds candidates; you approve.

    plan     the Curator reads each written chapter and plans its image slots (AI, JSON)
    find     licensed candidates from Wikimedia Commons (+ Pexels/Pixabay with keys);
             for "mixed" books, an AI illustration when nothing licensed fits a non-real subject
    you      approve one candidate per slot, generate more, upload your own, or skip the slot
    approve  the print-size file is downloaded into images/approved/

Rules the code enforces (not just the prompt):
  - real people/places/objects (`real_subject`) get licensed images only, never AI
  - image_strategy "licensed_web" never generates AI images; "ai_generated" searches only for real subjects
  - every AI prompt forbids text, letters, logos and brand names (an early test image
    painted a trademarked brand name on a toy box)
"""

from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from bookguild import prompts
from bookguild.chapters import read_file, strip_markers
from bookguild.events import EventBus, Status
from bookguild.gateway import AIGateway
from bookguild.images import APPROVED, NEW, REJECTED, SLOT_APPROVED, SLOT_NEEDS_CHOICE, Candidate, ImageSlot
from bookguild.models import ModelProfile
from bookguild.outline import Outline
from bookguild.profile import BookProfile
from bookguild.reliability import LLMError, PermanentError, RetryPolicy, TransientError, with_retries
from bookguild.research.image_search import ImageHit, ImageSearch
from bookguild.stages.research import book_summary
from bookguild.storage import Book

RESULTS_PER_QUERY = 3  # from each search phrase…
MAX_NEW_CANDIDATES = 9  # …pooled, up to this many new candidates per search round
AI_RULES = ("Rules: no text, letters, numbers, captions, logos, labels or brand names anywhere in the image. "
            "Do not depict any recognisable real person. Suitable for a children's book.")


@dataclass
class ImageJob:
    book: Book
    profile: BookProfile
    outline: Outline
    gateway: AIGateway
    models: ModelProfile
    search: ImageSearch
    bus: EventBus
    policy: RetryPolicy = field(default_factory=RetryPolicy)


def policy_text(strategy: str) -> str:
    return {
        "licensed_web": "Use only licensed photos and archive images (source must be \"licensed\").",
        "ai_generated": "Use AI illustrations (source \"ai\") except for real subjects, which must stay \"licensed\".",
        "mixed": "Use licensed photos for real people, places and objects; AI illustrations for ideas and scenes.",
    }.get(strategy, "No images.")


# ---------- planning ----------

async def plan_chapter(job: ImageJob, number: int, count: int) -> list[ImageSlot]:
    """Plan the chapter's images: always ONE chapter-opener image (chosen with the whole chapter in
    mind), then up to `count` - 1 section images, only where a picture really helps."""
    chapter = strip_markers(read_file(job.book, number, "final.md"))
    if not chapter:
        return []
    prompt = prompts.render("curator", book_summary=book_summary(job.profile), audience_age=job.profile.audience_age,
                            image_style=job.profile.image_style or "the book's style",
                            policy=policy_text(job.profile.image_strategy), extra=str(max(0, count - 1)),
                            number=str(number),
                            title=job.outline.chapters[number - 1].title, chapter=chapter)
    result = await job.gateway.chat_json(agent="Curator", stage="images", model=job.models.default,
                                         fallback_model=job.models.fallback, max_tokens=3000, thinking="off",
                                         messages=[{"role": "user", "content": prompt}], required_keys=("images",),
                                         validate=_images_list)
    planned = [raw for raw in result.data["images"] if isinstance(raw, dict) and _text(raw.get("purpose"))]
    openers = [raw for raw in planned if raw.get("role") == "chapter"]
    opener = openers[0] if openers else (planned[0] if planned else None)  # exactly one opener, first
    planned = ([opener] if opener else []) + [raw for raw in planned if raw is not opener][:max(0, count - 1)]
    slots = []
    for i, raw in enumerate(planned, start=1):
        real = bool(raw.get("real_subject")) or depicts_named_person(
            f"{raw.get('purpose', '')} {raw.get('ai_prompt') or ''}", chapter)
        source = "ai" if str(raw.get("source")) == "ai" else "licensed"
        if real or job.profile.image_strategy == "licensed_web":
            source = "licensed"  # enforced: real subjects are never AI-generated
        elif job.profile.image_strategy == "ai_generated":
            source = "ai"
        purpose = str(raw["purpose"]).strip()
        raw_queries = raw.get("search_queries") or []
        if isinstance(raw_queries, str):
            raw_queries = [raw_queries]
        queries = [_text(q) for q in raw_queries if isinstance(q, str) and _text(q)]
        queries = queries or [_text(raw.get("search_query")) or purpose[:60]]
        slots.append(ImageSlot(id=f"ch{number:02d}-{i}", chapter=number, purpose=purpose,
                               caption=_text(raw.get("caption")), anchor=_text(raw.get("anchor")),
                               source=source, real_subject=real, role="chapter" if raw is opener else "section",
                               search_queries=list(dict.fromkeys(queries))[:5],
                               ai_prompt=_text(raw.get("ai_prompt")) or purpose))
    return slots


# ---------- candidates ----------

async def find_licensed(job: ImageJob, slot: ImageSlot, queries: list[str] | None = None) -> int:
    """Search every phrase (specific → wider) and pool the results, so there is a real choice.
    Skips files the slot already has. Returns how many candidates were added."""
    known = {c.full_url for c in slot.candidates}
    added = 0
    pooled = []
    for query in queries or slot.queries():
        for provider in job.search.providers():
            try:
                hits = await search_with_shorter_query(job, provider, query)
            except LLMError as error:
                job.bus.log(f"{provider} search '{query}' failed for {slot.id}: {error.message}", "warning",
                            "images", "Curator")
                continue
            pooled.append((query, hits[:RESULTS_PER_QUERY]))
    # Round-robin across phrases/providers so broad searches remain represented.
    for index in range(RESULTS_PER_QUERY):
        for query, hits in pooled:
            for hit in hits[index:index + 1]:
                if hit.full_url in known or added >= MAX_NEW_CANDIDATES:
                    continue
                try:
                    await add_hit(job, slot, hit, query)
                except LLMError as error:
                    job.bus.log(f"Skipped a {provider} image ({error.message})", "warning", "images", "Curator")
                    continue
                known.add(hit.full_url)
                added += 1
    if not added:
        job.bus.log(f"{slot.id}: no new licensed images for {', '.join(queries or slot.queries())}", stage="images",
                    agent="Curator")
    return added


async def search_with_shorter_query(job: ImageJob, provider: str, query: str) -> list[ImageHit]:
    """Search; if nothing comes back, try again with just the names in the query (Commons search is
    literal: "Homi Bhabha 1930s portrait" finds nothing, "Homi Bhabha" finds several photos)."""
    def on_retry(error, attempt, delay):
        job.bus.log(f"{error.message} - retry {attempt}", "warning", "images", "Curator")

    hits = await with_retries(lambda: job.search.search(provider, query, RESULTS_PER_QUERY), job.policy,
                              asyncio.sleep, on_retry)
    names = " ".join(re.findall(r"\b[A-Z][\w.'-]+", query))
    if not hits and names and names != query:
        job.bus.log(f"No results for '{query}' - trying '{names}'", stage="images", agent="Curator")
        hits = await with_retries(lambda: job.search.search(provider, names, RESULTS_PER_QUERY), job.policy,
                                  asyncio.sleep, on_retry)
    return hits


async def add_hit(job: ImageJob, slot: ImageSlot, hit: ImageHit, query: str = "") -> Candidate:
    candidate_id = slot.next_candidate_id()
    preview = await job.search.download(hit.preview_url)
    relative = f"images/candidates/{slot.id}/{candidate_id}{_extension(hit.preview_url)}"
    _write(job.book, relative, preview)
    candidate = Candidate(id=candidate_id, provider=hit.provider, title=hit.title, preview=relative,
                          full_url=hit.full_url, page_url=hit.page_url, author=hit.author, license=hit.license,
                          license_url=hit.license_url, width=hit.width, height=hit.height, found_by=query)
    slot.candidates.append(candidate)
    return candidate


async def generate_ai(job: ImageJob, slot: ImageSlot) -> Candidate:
    """One AI illustration for the slot. Refused for real subjects."""
    if slot.real_subject:
        raise PermanentError(f"{slot.id} shows a real subject - only licensed images or your own upload",
                             use_fallback=False)
    style = job.profile.image_style or "warm, painterly children's book illustration"
    prompt = f"{slot.ai_prompt}\nStyle: {style}.\n{AI_RULES}"
    job.bus.set_agent_status("Curator", Status.RUNNING, f"painting {slot.id}", "images")
    result = await job.gateway.generate_image(agent="Curator", stage="images", model=job.models.image, prompt=prompt)
    candidate_id = slot.next_candidate_id()
    relative = f"images/candidates/{slot.id}/{candidate_id}.png"
    _write(job.book, relative, result.images[0])
    width, height = image_size(job.book.folder / relative)
    candidate = Candidate(id=candidate_id, provider="ai", title=slot.purpose, preview=relative, author="AI",
                          license="AI-generated", width=width, height=height, ai_model=result.model, prompt=prompt)
    slot.candidates.append(candidate)
    return candidate


async def fill_slot(job: ImageJob, slot: ImageSlot) -> None:
    """First candidates for a new slot, following the book's image strategy."""
    strategy = job.profile.image_strategy
    if slot.source == "licensed" and (strategy != "ai_generated" or slot.real_subject):
        await find_licensed(job, slot)
    if slot.source == "ai" or (strategy == "mixed" and not slot.candidates and not slot.real_subject):
        await generate_ai(job, slot)
    if not slot.candidates:
        job.bus.log(f"{slot.id}: nothing suitable found - upload your own image, or skip it", "warning",
                    "images", "Curator")


async def approve(job: ImageJob, slot: ImageSlot, candidate_id: str) -> None:
    """Make this candidate the slot's image; the print-size file goes to images/approved/."""
    candidate = slot.candidate(candidate_id)
    if candidate is None:
        raise PermanentError(f"no candidate {candidate_id} in {slot.id}", use_fallback=False)
    if candidate.full_url:
        data = await with_retries(lambda: job.search.download(candidate.full_url), job.policy, asyncio.sleep)
        extension = _extension(candidate.full_url)
    else:  # AI images and uploads are already full size
        data = (job.book.folder / candidate.preview).read_bytes()
        extension = Path(candidate.preview).suffix
    relative = f"images/approved/{slot.id}{extension}"
    for old in (job.book.folder / "images/approved").glob(f"{slot.id}.*"):
        old.unlink()
    _write(job.book, relative, data)
    width, height = image_size(job.book.folder / relative)
    if width:
        candidate.width, candidate.height = width, height
    for other in slot.candidates:
        if other.status == APPROVED:
            other.status = NEW
    candidate.status, slot.chosen, slot.file, slot.status = APPROVED, candidate.id, relative, SLOT_APPROVED


def reject(book: Book, slot: ImageSlot, candidate_id: str) -> None:
    candidate = slot.candidate(candidate_id)
    if candidate is None:
        return
    paths = [candidate.preview]
    if slot.chosen == candidate_id and slot.file:
        paths.append(slot.file)
    image_root = (book.folder / "images").resolve()
    for relative in set(paths):
        if not relative:
            continue
        path = (book.folder / relative).resolve()
        # Manifests may have been edited: never remove a user's original upload
        # or anything outside this book's managed image files.
        if path.is_relative_to(image_root) and path.is_file():
            path.unlink()
    candidate.status = REJECTED
    if slot.chosen == candidate_id:
        slot.chosen, slot.file, slot.status = "", "", SLOT_NEEDS_CHOICE


def upload(book: Book, slot: ImageSlot, source: Path) -> Candidate:
    """Your own image: copied into the book and approved at once."""
    candidate_id = slot.next_candidate_id()
    relative = f"images/candidates/{slot.id}/{candidate_id}{source.suffix.lower()}"
    (book.folder / relative).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, book.folder / relative)
    width, height = image_size(book.folder / relative)
    if not width:
        raise PermanentError(f"{source.name} is not an image the app can read", use_fallback=False)
    candidate = Candidate(id=candidate_id, provider="upload", title=source.stem, preview=relative,
                          author="the author", license="user-provided", width=width, height=height)
    slot.candidates.append(candidate)
    return candidate


# ---------- helpers ----------

def image_size(path: Path) -> tuple[int, int]:
    from PySide6.QtGui import QImageReader

    size = QImageReader(str(path)).size()
    return (size.width(), size.height()) if size.isValid() else (0, 0)


def _write(book: Book, relative: str, data: bytes) -> None:
    path = book.folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _extension(url: str) -> str:
    name = url.split("?")[0].lower()
    return ".png" if name.endswith(".png") else ".jpg"


PERSON_WORDS = re.compile(r"\b(young|child|childhood|boy|girl|man|woman|teenager|student|portrait|face|"
                          r"himself|herself|he|she|his|her|as a)\b", re.IGNORECASE)


def depicts_named_person(description: str, chapter: str) -> bool:
    """Code-level safety net for the real-subject rule: does the image description show a person
    who is a main character of the chapter? (A cheap Curator marked "young Chandru Raman as a
    child" as an AI idea in testing.) "Bhabha scattering" has no person words, so it stays an idea."""
    if not PERSON_WORDS.search(description):
        return False
    names = set(re.findall(r"\b[A-Z][a-z]{2,}\b", description))
    return any(len(re.findall(rf"\b{name}\b", chapter)) >= 3 for name in names)


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _images_list(data) -> None:
    if not isinstance(data.get("images"), list) or not data["images"]:
        raise TransientError("Curator reply had no images list")
    if not any(isinstance(raw, dict) and _text(raw.get("purpose")) for raw in data["images"]):
        raise TransientError("Curator reply had no usable image plans")
