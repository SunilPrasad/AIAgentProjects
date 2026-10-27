"""Stage 6 - Cover: the Illuminator proposes 3 concepts and the blurb; you choose or upload your own art.

    concepts  the Illuminator writes the blurb and 3 concepts (palette + text-free art prompt) (AI, JSON)
    art       each concept's front art is painted in portrait 2:3 at 2K (about 277 dpi on 6x9) -
              skipped when you uploaded your own front art
    you       pick a concept (or upload front/back art), edit title/subtitle/author/blurb/colours
    render    the app draws the typography and writes cover/wrap.png + wrap.pdf + ebook.jpg

The app, not the AI, draws all text: image models misspell words and add stray letters.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from bookguild import prompts
from bookguild.cover import CoverConcept, CoverSpec
from bookguild.events import EventBus
from bookguild.gateway import AIGateway
from bookguild.models import ModelProfile
from bookguild.outline import Outline
from bookguild.profile import BookProfile
from bookguild.reliability import LLMError, TransientError
from bookguild.stages.research import book_summary
from bookguild.storage import Book

ART_RULES = ("Book cover artwork only. Absolutely no text, letters, numbers, titles, captions, logos, signatures "
             "or brand names. No recognisable real person.")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass
class CoverJob:
    book: Book
    profile: BookProfile
    outline: Outline
    gateway: AIGateway
    models: ModelProfile
    bus: EventBus


async def propose(job: CoverJob, spec: CoverSpec) -> CoverSpec:
    """Blurb + 3 concepts; paint art for each unless you uploaded your own front art."""
    outline = job.outline
    prompt = prompts.render("illuminator", book_summary=book_summary(job.profile), title=outline.title,
                            subtitle=outline.subtitle or "-", pitch=outline.pitch or "-",
                            chapters="; ".join(c.title for c in outline.chapters),
                            audience_age=job.profile.audience_age,
                            image_style=job.profile.image_style or "the book's style")
    result = await job.gateway.chat_json(agent="Illuminator", stage="cover", model=job.models.default,
                                         fallback_model=job.models.fallback, max_tokens=3000, thinking="off",
                                         messages=[{"role": "user", "content": prompt}],
                                         required_keys=("blurb", "concepts"), validate=_three_concepts)
    spec.blurb = spec.blurb or str(result.data["blurb"]).strip()
    spec.title, spec.subtitle = spec.title or outline.title, spec.subtitle or outline.subtitle
    spec.concepts = [concept_from(raw, "ABC"[i]) for i, raw in enumerate(result.data["concepts"][:3])]

    if spec.front_art and not spec.front_art.startswith("cover/concepts/"):
        job.bus.log("You uploaded front art, so no concept art was painted - pick colours from a concept.",
                    stage="cover", agent="Illuminator")
        return spec
    results = await asyncio.gather(*(paint(job, concept) for concept in spec.concepts), return_exceptions=True)
    for concept, outcome in zip(spec.concepts, results):
        if isinstance(outcome, LLMError):
            job.bus.log(f"Concept {concept.id} art failed: {outcome.message}", "warning", "cover", "Illuminator")
        elif isinstance(outcome, Exception):
            raise outcome
    return spec


async def paint(job: CoverJob, concept: CoverConcept) -> None:
    from bookguild.image_style import REFERENCE_GUIDANCE, reference_data_urls

    references = reference_data_urls(job.book)
    prompt = f"{concept.art_prompt}\nBook-wide image instructions: {job.profile.image_style}\n{ART_RULES}"
    if references:
        prompt += f"\n{REFERENCE_GUIDANCE}"
    result = await job.gateway.generate_image(agent="Illuminator", stage="cover", model=job.models.cover_image,
                                              prompt=prompt, aspect_ratio="2:3", size="2K",
                                              reference_images=references)
    relative = f"cover/concepts/{concept.id}.png"
    path = job.book.folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(result.images[0])
    concept.art_file, concept.model = relative, result.model


def concept_from(raw: dict, concept_id: str) -> CoverConcept:
    def colour(key: str, default: str) -> str:
        value = str(raw.get(key, "")).strip()
        return value if HEX.match(value) else default

    return CoverConcept(id=concept_id, name=str(raw.get("name", f"Concept {concept_id}")).strip(),
                        art_prompt=str(raw.get("art_prompt", "")).strip(),
                        background=colour("background", "#1f2a44"), text_color=colour("text_color", "#ffffff"),
                        accent=colour("accent", "#f2c14e"),
                        title_position="bottom" if str(raw.get("title_position")) == "bottom" else "top")


def choose(spec: CoverSpec, concept_id: str) -> None:
    """Use a concept's art and colours (keeps your uploaded art if you have any)."""
    concept = next((c for c in spec.concepts if c.id == concept_id), None)
    if concept is None:
        return
    spec.chosen = concept.id
    spec.background, spec.text_color, spec.accent = concept.background, concept.text_color, concept.accent
    spec.title_position = concept.title_position
    if concept.art_file and (not spec.front_art or spec.front_art.startswith("cover/concepts/")):
        spec.front_art = concept.art_file
        spec.art_has_text = False


def upload(book: Book, spec: CoverSpec, side: str, source: Path) -> str:
    """Your own front or back art, copied into cover/."""
    from shutil import copyfile

    relative = f"cover/{side}-art{source.suffix.lower()}"
    (book.folder / "cover").mkdir(parents=True, exist_ok=True)
    for old in (book.folder / "cover").glob(f"{side}-art.*"):
        old.unlink()
    copyfile(source, book.folder / relative)
    if side == "front":
        spec.front_art = relative
    else:
        spec.back_art = relative
    return relative


def _three_concepts(data) -> None:
    concepts = data.get("concepts")
    if not isinstance(concepts, list) or len(concepts) < 2 or not all(isinstance(c, dict) for c in concepts):
        raise TransientError("Illuminator reply needs at least 2 concepts")
