"""Stage 3 - Title & outline: the Architects propose, the Council picks, you approve.

  1. Each Architect (Architect-i uses the model of Scribe-i, so they come from different
     providers) proposes a title, subtitle, pitch and chapter outline from the profile,
     the brief and the research brief. They work at the same time.
  2. The Council judges the proposals blind (see jury.py) with a rubric that puts fitting
     the brief and being supported by the research first.
  3. The winner becomes the working outline; the Chair's note says how to improve it.
     You can apply the note, switch to another proposal, edit, and approve.

At least two proposals are needed for a vote. These functions do the AI work and return
data; BookSession saves it and moves the stage along.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from bookguild import prompts, storage
from bookguild.events import EventBus
from bookguild.gateway import AIGateway
from bookguild.jury import Criterion, Verdict, judge
from bookguild.models import ModelProfile
from bookguild.outline import Outline, Proposal
from bookguild.profile import BookProfile
from bookguild.reliability import LLMError, PermanentError, TransientError
from bookguild.stages.research import read_topic_brief
from bookguild.storage import Book

MAX_ARCHITECTS = 3
RESEARCH_CHARS = 40_000  # how much of the research brief the Architects read
JURY_RESEARCH_CHARS = 20_000  # jurors get a shorter excerpt to check claims against
MAX_TOKENS = 8000


@dataclass
class OutlineJob:
    book: Book
    profile: BookProfile
    gateway: AIGateway
    models: ModelProfile
    bus: EventBus


def rubric_for(profile: BookProfile) -> list[Criterion]:
    evidence = profile.mode == "evidence"
    return [
        Criterion("fit", "Covers the brief and every must-include topic; matches the profile (kind of book, "
                         "audience, roughly the planned number of chapters).", 3),
        Criterion("accuracy", "Every chapter is supported by the research; nothing is invented, exaggerated or "
                              "promised that the research can't deliver." if evidence else
                              "Internally consistent; nothing contradicts the brief.", 3 if evidence else 1),
        Criterion("audience", f"Right for readers aged {profile.audience_age} at a "
                              f"'{profile.reading_level}' reading level.", 2),
        Criterion("structure", "Logical order and arc; chapters are balanced and distinct, with no overlaps or "
                               "gaps.", 2),
        Criterion("appeal", "Title, subtitle and pitch would make the target reader pick it up on Amazon, "
                            "without misleading.", 1),
    ]


def architect_names(models: ModelProfile) -> list[str]:
    return [f"Architect-{i + 1}" for i in range(min(MAX_ARCHITECTS, len(models.scribes)))]


async def propose(job: OutlineJob) -> list[Proposal]:
    """All Architects at once. Failed Architects are skipped (their failure is already reported)."""
    research = read_topic_brief(job.book)[:RESEARCH_CHARS]
    results = await asyncio.gather(*(propose_one(job, name, research) for name in architect_names(job.models)),
                                   return_exceptions=True)
    proposals = []
    for result in results:
        if isinstance(result, Proposal):
            proposals.append(result)
        elif not isinstance(result, LLMError):
            raise result  # a programming error - don't hide it
    return proposals


async def propose_one(job: OutlineJob, architect: str, research: str) -> Proposal:
    prompt = prompts.render("architect", architect=architect, profile=job.profile.for_prompt(),
                            brief=storage.read_brief(job.book), research=research,
                            chapter_count=str(job.profile.chapter_count))
    result = await job.gateway.chat_json(
        agent=architect, stage="outline", model=job.models.model_for(architect), fallback_model=job.models.fallback,
        messages=[{"role": "user", "content": prompt}], max_tokens=MAX_TOKENS, thinking="off",
        required_keys=("title", "chapters"), validate=_has_chapters,
    )
    outline, warnings = Outline.from_dict(result.data)
    for warning in warnings:
        job.bus.log(warning, "warning", "outline", architect)
    if len(outline.chapters) != job.profile.chapter_count:
        job.bus.log(f"Planned {len(outline.chapters)} chapters (profile asks for {job.profile.chapter_count})",
                    "warning", "outline", architect)
    job.bus.log(f"Proposed '{outline.title}' with {len(outline.chapters)} chapters", stage="outline",
                agent=architect)
    return Proposal(architect=architect, model=result.model, outline=outline)


async def run(job: OutlineJob) -> tuple[list[Proposal], Verdict]:
    proposals = await propose(job)
    if len(proposals) < 2:
        raise PermanentError(f"only {len(proposals)} Architect proposal(s) - at least 2 are needed for a vote",
                             use_fallback=False)
    job.bus.log(f"The Council is judging {len(proposals)} proposals…", stage="outline", agent="Chair")
    verdict = await judge(job.gateway, job.models, "outline", task=task_text(job.profile),
                          context=jury_context(job), candidates=[p.outline.as_text() for p in proposals],
                          rubric=rubric_for(job.profile))
    return proposals, verdict


async def revise(job: OutlineJob, outline: Outline, instruction: str, architect: str = "Architect-1") -> Outline:
    """Revise an outline as instructed (your words, or the Chair's note)."""
    prompt = prompts.render("architect_revise", architect=architect, profile=job.profile.for_prompt(),
                            research=read_topic_brief(job.book)[:RESEARCH_CHARS],
                            outline=json.dumps(outline.to_dict(), ensure_ascii=False, indent=1),
                            instruction=instruction)
    result = await job.gateway.chat_json(
        agent=architect, stage="outline", model=job.models.model_for(architect), fallback_model=job.models.fallback,
        messages=[{"role": "user", "content": prompt}], max_tokens=MAX_TOKENS, thinking="off",
        required_keys=("title", "chapters"), validate=_has_chapters,
    )
    revised, warnings = Outline.from_dict(result.data)
    for warning in warnings:
        job.bus.log(warning, "warning", "outline", architect)
    return revised


def task_text(profile: BookProfile) -> str:
    return (f"Propose a title, subtitle, pitch and a {profile.chapter_count}-chapter outline for the book "
            f"'{profile.working_title}' ({profile.mode} book for readers aged {profile.audience_age}).")


def jury_context(job: OutlineJob) -> str:
    profile = job.profile
    return (f"Book Profile:\n{profile.for_prompt()}\n\nThe author's brief:\n{storage.read_brief(job.book)}\n\n"
            f"Research brief (excerpt; source ids like [S4]):\n{read_topic_brief(job.book)[:JURY_RESEARCH_CHARS]}")


def _has_chapters(data) -> None:
    chapters = data.get("chapters") if isinstance(data, dict) else None
    if not isinstance(chapters, list) or not chapters:
        raise TransientError("Outline had no chapters")
