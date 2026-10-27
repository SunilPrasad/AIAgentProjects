"""BookSession: runs the pipeline for the open book and understands chat commands.

This is the "conductor" between the UI and the stages:
- the UI calls its methods (button clicks, chat messages)
- it runs stage functions, saves results, updates stage statuses
- it reports everything through the EventBus (it never touches widgets)

Only one AI step runs at a time per book (`busy`), so a double click or a chat
command can never start the same paid work twice.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from dataclasses import dataclass, field, replace
from typing import Awaitable, Callable

from bookguild import prompts, storage
from bookguild.budget import format_usd
from bookguild.chapters import ChapterRecord, load_records, save_records
from bookguild.cover import (
    BLEED_IN,
    CoverSpec,
    estimate_pages,
    export_cover,
    load_cover,
    save_cover,
    spine_width_in,
    trim_inches,
)
from bookguild.images import SLOT_APPROVED, SLOT_SKIPPED, ImageSlot, load_slots, save_slots
from bookguild.events import EventBus, Status
from bookguild.gateway import AIGateway
from bookguild.models import SEARCH_PROVIDERS, ModelProfile
from bookguild.profile import BookProfile, load_profile, save_profile
from bookguild.outline import (
    Outline,
    load_outline,
    load_proposals,
    load_verdict,
    save_outline,
    save_proposals,
    save_verdict,
)
from bookguild.reliability import Failure, LLMError, PermanentError
from bookguild.research.search import SearchClient
from bookguild.research.sources import HIGH_QUALITY, SourceRegistry, load_sources, save_sources
from bookguild.stages import profile as profile_stage
from bookguild.stages import chapters as chapters_stage
from bookguild.stages import cover as cover_stage
from bookguild.stages import images as images_stage
from bookguild.stages import outline as outline_stage
from bookguild.stages import research as research_stage
from bookguild.storage import STAGE_LABELS, Book

MakeGateway = Callable[..., AIGateway]  # make_gateway(step_retry=...) -> AIGateway

MakeSearch = Callable[[ModelProfile], SearchClient]  # make_search(models) -> SearchClient

ACTIONS = ("generate_profile", "revise_profile", "set_profile_field", "approve_profile",
           "run_research", "exclude_source", "include_source",
           "run_outline", "revise_outline", "apply_chair_note", "choose_proposal", "approve_outline", "approve",
           "write_chapters", "rewrite_chapter", "revise_chapter", "plan_images", "generate_image", "skip_image",
           "make_cover", "set_author", "approve_cover",
           "show_status", "show_cost", "help", "none")

HELP_TEXT = (
    "You can say things like: 'draft the profile', 'make it for teenagers', 'set target_pages to 120', "
    "'approve', 'run research', 'exclude S4', 'make the outline', 'apply the chair's note', 'use proposal B', "
    "'add a chapter on Janaki Ammal', 'write the chapters', 'write chapter 3', 'rewrite chapter 3', "
    "'make chapter 2 simpler', 'find images', 'generate image ch01-2', 'skip image ch01-2', 'make the cover', "
    "'author is Jane Doe', 'approve cover', 'status' or 'cost'. Export arrives in the next phase."
)


@dataclass
class Command:
    action: str
    args: dict = field(default_factory=dict)
    reply: str = ""


# Simple commands understood without asking an AI (instant and free).
QUICK_COMMANDS = [
    (r"(approve|approved|ok,? approve|looks good)", "approve"),
    (r"approve( the)? profile", "approve_profile"),
    (r"approve( the)? outline", "approve_outline"),
    (r"((run|make|create|draft|build)( the)? )?outline", "run_outline"),
    (r"apply( the)? chair'?s? note", "apply_chair_note"),
    (r"write( all)?( the)?( remaining)? chapters", "write_chapters"),
    (r"(find|plan|get)( the)? images", "plan_images"),
    (r"(make|design|create)( the)? cover( concepts)?", "make_cover"),
    (r"approve( the)? cover", "approve_cover"),
    (r"(status|where are we)", "show_status"),
    (r"(cost|costs|show cost|spent|spend)", "show_cost"),
    (r"(help|\?)", "help"),
    (r"(generate|draft|create|make)( the)? profile", "generate_profile"),
    (r"((run|start|do)( the)? )?research", "run_research"),
]


def quick_command(text: str) -> Command | None:
    cleaned = text.strip().lower().rstrip(".!?") or text.strip()
    for pattern, action in QUICK_COMMANDS:
        if re.fullmatch(pattern, cleaned):
            return Command(action)
    match = re.fullmatch(r"set (\w+) (?:to|=) (.+)", text.strip(), flags=re.IGNORECASE)
    if match:
        return Command("set_profile_field", {"field": match.group(1).lower(), "value": match.group(2).strip()})
    match = re.fullmatch(r"(?:set (?:the )?)?author(?:'s name)? (?:is|to|=) (.+)", text.strip().rstrip("."),
                         flags=re.IGNORECASE)
    if match:
        return Command("set_author", {"name": match.group(1).strip()})
    match = re.fullmatch(r"(generate|skip) image (ch\d+-\d+)", cleaned)
    if match:
        return Command(f"{match.group(1)}_image", {"slot_id": match.group(2)})
    match = re.fullmatch(r"(write|rewrite) chapter (\d+)", cleaned)
    if match:
        number = int(match.group(2))
        return Command("write_chapters", {"numbers": [number]}) if match.group(1) == "write" else \
            Command("rewrite_chapter", {"number": number})
    match = re.fullmatch(r"(?:use|choose|pick) proposal ([a-h])", cleaned)
    if match:
        return Command("choose_proposal", {"index": "ABCDEFGH".index(match.group(1).upper())})
    match = re.fullmatch(r"(exclude|include) (?:source )?(s\d+)", cleaned)
    if match:
        return Command(f"{match.group(1)}_source", {"source_id": match.group(2).upper()})
    return None


class BookSession:
    def __init__(self, book: Book, bus: EventBus, make_gateway: MakeGateway, models: Callable[[], ModelProfile],
                 make_search: MakeSearch | None = None, make_image_search=None):
        self.book = book
        self.bus = bus
        self.make_gateway = make_gateway
        self.models = models  # returns the active model profile
        self.make_search = make_search  # creates the web search client for the Scouts
        self.make_image_search = make_image_search  # creates the licensed image search for the Curator
        self.busy: str | None = None  # description of the running step, or None

    @property
    def profile(self) -> BookProfile | None:
        return load_profile(self.book)

    def set_stage(self, stage: str, status: str) -> None:
        self.book.stages[stage] = status
        storage.save_book(self.book)
        self.bus.set_stage_status(stage, status)

    # ---------- Stage 1: profile ----------

    async def generate_profile(self, instruction: str = "") -> BookProfile | None:
        """Draft the profile from the brief, or revise the existing one if `instruction` is given."""
        if self._refuse_if_busy():
            return None
        current = self.profile
        revising = bool(instruction and current)
        self.busy = "the Cartographer is revising the profile" if revising else "the Cartographer is drafting the profile"
        self.set_stage("profile", Status.RUNNING)
        self.bus.log(f"{self.busy[0].upper()}{self.busy[1:]}…", stage="profile", agent="Cartographer")
        gateway = self.make_gateway(step_retry=lambda: self.generate_profile(instruction))
        try:
            if revising:
                profile, warnings = await profile_stage.revise_profile(self.book, gateway, self.models(), current,
                                                                       instruction)
            else:
                profile, warnings = await profile_stage.draft_profile(self.book, gateway, self.models())
        except LLMError:
            self.set_stage("profile", Status.FAILED)
            return None
        finally:
            self.busy = None

        for warning in warnings:
            self.bus.log(f"Fixed a profile value: {warning}", "warning", "profile", "Cartographer")
        self._store(profile, approved=False)
        self.set_stage("profile", Status.WAITING)
        self.bus.log(f"Profile ready: {describe(profile)}. Review it in the Profile tab, then approve.",
                     "success", "profile", "Cartographer")
        return profile

    def save_profile(self, profile: BookProfile) -> None:
        """Your edits from the Profile tab. Editing always needs a fresh approval."""
        self._store(profile, approved=False)
        self.set_stage("profile", Status.WAITING)
        self.bus.log("Profile edits saved - waiting for your approval.", stage="profile", agent="You")

    def approve_profile(self, profile: BookProfile | None = None) -> str:
        profile = profile or self.profile
        if profile is None:
            return "There is no profile yet - say 'draft the profile' first."
        self._store(profile, approved=True)
        self.set_stage("profile", Status.DONE)
        self.bus.log("Profile approved.", "success", "profile", "You")
        return "Profile approved ✓. Research (the Scouts) arrives in Phase 4."

    def set_profile_field(self, name: str, value: str) -> str:
        current = self.profile
        if current is None:
            return "There is no profile yet - say 'draft the profile' first."
        data = current.to_dict()
        if name not in data or name == "approved":
            return f"'{name}' is not a profile field. Fields: {', '.join(k for k in data if k != 'approved')}."
        data[name] = value
        profile, warnings = BookProfile.from_dict(data)
        self.save_profile(profile)
        note = f" ({warnings[0]})" if warnings else ""
        return f"Set {name} to {getattr(profile, name)!s}{note}. Please approve the profile again."

    def _store(self, profile: BookProfile, approved: bool) -> None:
        profile.approved = approved
        save_profile(self.book, profile)
        self.book.budget_usd = profile.budget_usd
        if profile.working_title:
            self.book.title = profile.working_title
        storage.save_book(self.book)
        self.bus.profile_changed.emit(profile)
        self.bus.set_cost(self.book.spent_usd, self.book.budget_usd)

    # ---------- Stage 2: research ----------

    async def run_research(self) -> bool:
        """The three Scouts research the topic. Needs an approved profile. Re-running replaces the sources."""
        profile = self.profile
        if profile is None or not profile.approved:
            self.reply("Please approve the Book Profile first - the Scouts research what it describes.")
            return False
        if self._refuse_if_busy():
            return False
        self.busy = "the Scouts are researching"
        self.set_stage("research", Status.RUNNING)
        models = self.models()
        search = self.make_search(models)
        self.bus.log(f"Scouts set out: {', '.join(research_stage.SCOUT_ANGLES)} "
                     f"(web search: {SEARCH_PROVIDERS[models.search].label})", stage="research", agent="Steward")
        job = research_stage.ResearchJob(self.book, profile, self.make_gateway(step_retry=self.run_research),
                                         models, search, self.bus)
        try:
            reports, errors = await research_stage.run(job)
        finally:
            self.busy = None
            await search.close()

        for error in errors:
            self.bus.log(f"A Scout failed - {error}", "warning", "research")
        if not reports:
            self.set_stage("research", Status.FAILED)
            self.bus.research_changed.emit()
            return False
        sources = [s for s in load_sources(self.book) if not s.excluded]
        high = sum(1 for s in sources if s.quality >= HIGH_QUALITY)
        self.set_stage("research", Status.DONE)
        self.bus.log(f"Research done: {len(sources)} sources ({high} high quality) from {len(reports)} of "
                     f"{len(research_stage.SCOUT_ANGLES)} Scouts. Review them in the Research tab.",
                     "success", "research", "Steward")
        self.bus.research_changed.emit()
        return True

    def set_source_excluded(self, source_id: str, excluded: bool) -> str:
        sources = load_sources(self.book)
        source = next((s for s in sources if s.id == source_id.upper()), None)
        if source is None:
            return f"There is no source {source_id}."
        source.excluded = excluded
        save_sources(self.book, sources)
        research_stage.write_topic_brief(self.book, self.profile or BookProfile())
        self.bus.research_changed.emit()
        verb = "Excluded" if excluded else "Included"
        self.bus.log(f"{verb} {source.id} ({source.domain}).", stage="research", agent="You")
        return f"{verb} {source.id} - {source.title}. The research brief has been updated."

    # ---------- Stage 3: title & outline ----------

    @property
    def outline(self) -> Outline | None:
        return load_outline(self.book)

    async def run_outline(self) -> bool:
        """The Architects propose outlines and the Council picks one. Replaces the current outline."""
        profile = self.profile
        if profile is None or not profile.approved:
            self.reply("Please approve the Book Profile first.")
            return False
        if self.book.stages["research"] != Status.DONE:
            self.reply("Please run the research first - the Architects build the outline on it.")
            return False
        if self._refuse_if_busy():
            return False
        self.busy = "the Architects and the Council are working on the outline"
        self.set_stage("outline", Status.RUNNING)
        job = self._outline_job(step_retry=self.run_outline)
        try:
            proposals, verdict = await outline_stage.run(job)
        except LLMError as error:
            self._stage_failed("outline", "Chair", error, retry=self.run_outline)
            return False
        finally:
            self.busy = None

        save_proposals(self.book, proposals)
        save_verdict(self.book, {**verdict.to_dict(), "architects": [p.architect for p in proposals]})
        winner = proposals[verdict.winner]
        self._store_outline(winner.outline)
        label = "ABCDEFGH"[verdict.winner]
        self.bus.log(f"The Council chose proposal {label} by {winner.architect} ('{winner.outline.title}', "
                     f"{verdict.points[verdict.winner]} points). Review it in the Outline tab, then approve.",
                     "success", "outline", "Chair")
        return True

    async def revise_outline(self, instruction: str) -> bool:
        current = self.outline
        if current is None:
            self.reply("There is no outline yet - say 'make the outline' first.")
            return False
        if self._refuse_if_busy():
            return False
        self.busy = "an Architect is revising the outline"
        self.set_stage("outline", Status.RUNNING)
        job = self._outline_job(step_retry=lambda: self.revise_outline(instruction))
        try:
            revised = await outline_stage.revise(job, current, instruction, self._winning_architect())
        except LLMError as error:
            self._stage_failed("outline", self._winning_architect(), error, retry=None)
            return False
        finally:
            self.busy = None
        self._store_outline(revised)
        self.bus.log(f"Outline revised: '{revised.title}', {len(revised.chapters)} chapters. Please review and "
                     "approve.", "success", "outline", self._winning_architect())
        return True

    async def apply_chair_note(self) -> bool:
        verdict = load_verdict(self.book)
        note = (verdict or {}).get("chair_note", "")
        if not note:
            self.reply("There is no Chair's note to apply.")
            return False
        return await self.revise_outline(f"Apply the Council Chair's improvement note:\n{note}")

    def choose_proposal(self, index: int) -> str:
        proposals = load_proposals(self.book)
        if not 0 <= index < len(proposals):
            return f"There is no proposal {'ABCDEFGH'[index] if 0 <= index < 8 else index}."
        self._store_outline(proposals[index].outline)
        return f"Now using proposal {'ABCDEFGH'[index]} by {proposals[index].architect}. Edit it or approve it."

    def save_outline(self, outline: Outline) -> None:
        self._store_outline(outline)
        self.bus.log("Outline edits saved - waiting for your approval.", stage="outline", agent="You")

    def approve_outline(self, outline: Outline | None = None) -> str:
        outline = outline or self.outline
        if outline is None:
            return "There is no outline yet - say 'make the outline' first."
        if not outline.chapters:
            return "The outline has no chapters - add some before approving."
        outline.approved = True
        save_outline(self.book, outline)
        self.book.title = outline.title
        storage.save_book(self.book)
        self.set_stage("outline", Status.DONE)
        self.bus.outline_changed.emit()
        self.bus.log(f"Outline approved: '{outline.title}', {len(outline.chapters)} chapters.", "success",
                     "outline", "You")
        return f"Outline approved ✓ - '{outline.title}', {len(outline.chapters)} chapters. Say 'write the chapters'."

    def approve(self) -> str:
        """'approve' in chat: approve whatever is waiting for you, in pipeline order."""
        profile = self.profile
        if profile is not None and not profile.approved:
            return self.approve_profile()
        outline = self.outline
        if outline is not None and not outline.approved:
            return self.approve_outline()
        cover = load_cover(self.book)
        if cover is not None and not cover.approved:
            return self.approve_cover()
        return "Nothing is waiting for your approval right now."

    def _store_outline(self, outline: Outline) -> None:
        outline.approved = False
        save_outline(self.book, outline)
        self.set_stage("outline", Status.WAITING)
        self.bus.outline_changed.emit()

    def _winning_architect(self) -> str:
        verdict = load_verdict(self.book) or {}
        architects = verdict.get("architects") or ["Architect-1"]
        return architects[verdict.get("winner", 0)] if verdict.get("winner", 0) < len(architects) else "Architect-1"

    def _outline_job(self, step_retry) -> outline_stage.OutlineJob:
        return outline_stage.OutlineJob(self.book, self.profile, self.make_gateway(step_retry=step_retry),
                                        self.models(), self.bus)

    def _stage_failed(self, stage: str, agent: str, error: LLMError, retry) -> None:
        """Mark a stage failed. Errors the gateway didn't already report (e.g. too few votes) get a Failure row."""
        self.set_stage(stage, Status.FAILED)
        if isinstance(error, PermanentError) and error.status is None and error.attempts == 0:
            self.bus.log(f"FAILED: {error.message}", "error", stage, agent)
            self.bus.failure_added.emit(Failure(stage=stage, agent=agent, model="-", error=error.message,
                                                kind="permanent", attempts=1, retry=retry))

    # ---------- Stage 4: chapters ----------

    def chapter_records(self) -> list[ChapterRecord]:
        outline = self.outline
        return load_records(self.book, outline) if outline else []

    async def write_chapters(self, numbers: list[int] | None = None, instruction: str = "",
                             fresh: bool = False) -> bool:
        """Write chapters (default: every chapter not done yet). `fresh` throws away saved work first."""
        outline = self.outline
        if outline is None or not outline.approved:
            self.reply("Please approve the outline first - the Scribes write the chapters it plans.")
            return False
        records = load_records(self.book, outline)
        numbers = numbers or [r.number for r in records if r.status != Status.DONE]
        invalid = [n for n in numbers if not 1 <= n <= len(records)]
        if invalid:
            self.reply(f"There is no chapter {invalid[0]} - the outline has {len(records)}.")
            return False
        if not numbers:
            self.reply("All chapters are written. Say 'rewrite chapter 3' to redo one.")
            return False
        if self._refuse_if_busy():
            return False
        save_records(self.book, records)
        if fresh:
            for number in numbers:
                chapters_stage.clear_chapter(self.book, number)

        self.busy = f"the Guild is writing chapter(s) {', '.join(map(str, numbers))}"
        self.set_stage("chapters", Status.RUNNING)
        models = self.models()
        search = self.make_search(models)
        job = chapters_stage.ChapterJob(
            self.book, self.profile, outline, models, search, self.bus,
            registry=SourceRegistry(load_sources(self.book)), make_gateway=self.make_gateway,
            retry_chapter=lambda n: self.write_chapters([n]), on_update=self._update_chapter)
        self.bus.log(f"Writing chapter(s) {', '.join(map(str, numbers))} "
                     f"({chapters_stage.CHAPTERS_IN_PARALLEL} at a time)…", stage="chapters", agent="Steward")
        try:
            await chapters_stage.run(job, numbers, instruction)
        finally:
            self.busy = None
            await search.close()
        self._finish_chapters_stage()
        return True

    async def rewrite_chapter(self, number: int, instruction: str = "") -> bool:
        return await self.write_chapters([number], instruction=instruction, fresh=True)

    async def revise_chapter(self, number: int, instruction: str) -> bool:
        """Your change to a finished chapter: one revision plus the fact-check."""
        records = self.chapter_records()
        record = next((r for r in records if r.number == number), None)
        if record is None or record.status != Status.DONE:
            self.reply(f"Chapter {number} isn't written yet - say 'write chapter {number}' first.")
            return False
        if self._refuse_if_busy():
            return False
        self.busy = f"a Scribe is revising chapter {number}"
        models = self.models()
        search = self.make_search(models)
        job = chapters_stage.ChapterJob(
            self.book, self.profile, self.outline, models, search, self.bus,
            registry=SourceRegistry(load_sources(self.book)), make_gateway=self.make_gateway,
            retry_chapter=lambda n: self.revise_chapter(n, instruction), on_update=self._update_chapter)
        try:
            result = await chapters_stage.revise_chapter(job, number, instruction, record.winner or "Scribe-1")
        finally:
            self.busy = None
            await search.close()
        self.bus.log(f"Chapter {number} revised: {result.words} words, {result.flags} flag(s)."
                     if not result.error else f"Chapter {number}: {result.step} ({result.error})",
                     "success" if not result.error else "warning", "chapters", result.winner)
        return not result.error

    def _update_chapter(self, record: ChapterRecord) -> None:
        records = self.chapter_records()
        for i, existing in enumerate(records):
            if existing.number == record.number:
                records[i] = record
        save_records(self.book, records)
        self.bus.chapters_changed.emit(record.number)

    def _finish_chapters_stage(self) -> None:
        records = self.chapter_records()
        done = sum(r.status == Status.DONE for r in records)
        failed = sum(r.status == Status.FAILED for r in records)
        flags = sum(r.flags for r in records if r.status == Status.DONE)
        if done == len(records):
            self.set_stage("chapters", Status.DONE)
        else:
            self.set_stage("chapters", Status.FAILED if failed else Status.IDLE)
        self.bus.log(f"Chapters: {done} of {len(records)} written" + (f", {failed} failed" if failed else "")
                     + (f", {flags} fact-check flag(s) to review" if flags else ""),
                     "success" if done == len(records) and not flags else "warning", "chapters", "Steward")

    # ---------- Stage 5: images ----------

    def add_style_samples(self, paths: list[Path]) -> None:
        from bookguild.image_style import add_reference

        if self._refuse_if_busy():
            return
        for path in paths:
            try:
                add_reference(self.book, path)
            except (LLMError, OSError) as error:
                self.reply(str(error))
                break
        self.bus.style_samples_changed.emit()

    def remove_style_sample(self, relative: str) -> None:
        from bookguild.image_style import remove_reference

        if self._refuse_if_busy():
            return
        try:
            remove_reference(self.book, relative)
        except (LLMError, OSError) as error:
            self.reply(str(error))
        self.bus.style_samples_changed.emit()

    def image_slots(self) -> list[ImageSlot]:
        return load_slots(self.book)

    async def plan_images(self, chapters: list[int] | None = None) -> bool:
        """The Curator plans image slots for written chapters (not yet planned) and finds first candidates."""
        profile = self.profile
        if profile is None or profile.image_strategy == "none" or profile.images_per_chapter == 0:
            self.reply("The Book Profile says this book has no images. Change 'Image source' in the Profile tab "
                       "to add some.")
            return False
        written = [r.number for r in self.chapter_records() if r.status == Status.DONE]
        planned = {s.chapter for s in self.image_slots()}
        chapters = [n for n in (chapters or written) if n in written and n not in planned]
        if not chapters:
            self.reply("No new written chapters to plan images for. Write chapters first, or open a slot to find "
                       "more images.")
            return False
        if self._refuse_if_busy():
            return False
        self.busy = "the Curator is finding images"
        self.set_stage("images", Status.RUNNING)
        job = self._image_job()
        slots = self.image_slots()
        try:
            for number in chapters:
                try:
                    new_slots = await images_stage.plan_chapter(job, number, profile.images_per_chapter)
                except LLMError as error:
                    self.bus.log(f"Chapter {number}: image planning failed ({error.message})", "warning", "images",
                                 "Curator")
                    continue
                for slot in new_slots:
                    slots.append(slot)
                    await self._image_step(job, slot, images_stage.fill_slot(job, slot))
                    save_slots(self.book, slots)
                    self.bus.images_changed.emit()
        finally:
            self.busy = None
            await job.search.close()
        self._finish_images_stage()
        return True

    async def generate_chapter_image(self, number: int) -> bool:
        """Generate a whole-chapter opener, preserving existing section images and decisions."""
        profile, outline = self.profile, self.outline
        if (profile is None or outline is None or not 1 <= number <= len(outline.chapters) or
                not any(r.number == number and r.status == Status.DONE for r in self.chapter_records())):
            self.reply("Write that chapter first, then generate its chapter image.")
            return False
        if self._refuse_if_busy():
            return False
        self.busy = f"the Curator is generating chapter {number}'s opener"
        self.set_stage("images", Status.RUNNING)
        job = self._image_job()
        # This is an explicit AI request, independent of the automatic image policy.
        job.profile = replace(profile, image_strategy="ai_generated")
        slots = self.image_slots()
        try:
            opener = next((s for s in slots if s.chapter == number and s.role == "chapter"), None)
            if opener is None:
                planned = await images_stage.plan_chapter(job, number, 1)
                if not planned:
                    self.reply("That chapter has no final text to illustrate.")
                    return False
                opener = planned[0]
                index = 1
                while any(s.id == f"ch{number:02d}-{index}" for s in slots):
                    index += 1
                opener.id = f"ch{number:02d}-{index}"
                slots.append(opener)
                slots.sort(key=lambda s: (s.chapter, s.role != "chapter", s.id))
                save_slots(self.book, slots)  # retry generation without paying to plan again
                self.bus.images_changed.emit()
            ok = await self._image_step(job, opener, images_stage.generate_ai(job, opener))
            save_slots(self.book, slots)
            return ok
        except LLMError as error:
            self.reply(f"Could not plan the chapter image: {error.message}")
            return False
        finally:
            self.busy = None
            await job.search.close()
            self._finish_images_stage()

    async def find_more_images(self, slot_id: str, query: str = "") -> bool:
        """Search again with the slot's phrases, or with your own words (`query`)."""
        if self.profile and self.profile.image_strategy in ("none", "ai_generated"):
            self.reply("The profile uses AI-generated images. Use Generate AI image for this slot.")
            return False
        queries = [query.strip()] if query.strip() else None
        return await self._slot_action(slot_id, f"searching for '{query}'" if queries else "finding more images",
                                       lambda job, slot: images_stage.find_licensed(job, slot, queries))

    async def generate_image(self, slot_id: str) -> bool:
        return await self._slot_action(slot_id, "painting an AI image",
                                       lambda job, slot: images_stage.generate_ai(job, slot))

    async def approve_image(self, slot_id: str, candidate_id: str) -> bool:
        return await self._slot_action(slot_id, "downloading the print-size image",
                                       lambda job, slot: images_stage.approve(job, slot, candidate_id))

    def reject_image(self, slot_id: str, candidate_id: str) -> None:
        if self._refuse_if_busy():
            return
        try:
            self._edit_slot(slot_id, lambda slot: images_stage.reject(self.book, slot, candidate_id))
        except OSError as error:
            self.reply(f"Could not delete the rejected image: {error}")

    def skip_image(self, slot_id: str) -> str:
        def skip(slot: ImageSlot) -> None:
            slot.status, slot.chosen, slot.file = SLOT_SKIPPED, "", ""
        return "Skipped." if self._edit_slot(slot_id, skip) else f"There is no image slot {slot_id}."

    def upload_image(self, slot_id: str, path: Path) -> str:
        def do_upload(slot: ImageSlot) -> None:
            candidate = images_stage.upload(self.book, slot, path)
            for other in slot.candidates:
                if other.status == "approved":
                    other.status = "new"
            candidate.status, slot.chosen, slot.status = "approved", candidate.id, SLOT_APPROVED
            slot.file = candidate.preview
        try:
            found = self._edit_slot(slot_id, do_upload)
        except LLMError as error:
            return error.message
        return f"Your image is now used for {slot_id}." if found else f"There is no image slot {slot_id}."

    def add_image_slot(self, chapter: int, purpose: str, real_subject: bool) -> str:
        slots = self.image_slots()
        number = 1 + sum(1 for s in slots if s.chapter == chapter)
        slot_id = f"ch{chapter:02d}-{number}"
        while any(s.id == slot_id for s in slots):
            number += 1
            slot_id = f"ch{chapter:02d}-{number}"
        slots.append(ImageSlot(id=slot_id, chapter=chapter, purpose=purpose, caption=purpose,
                               source="licensed" if real_subject else "ai", search_queries=[purpose[:60]],
                               ai_prompt=purpose, real_subject=real_subject))
        slots.sort(key=lambda s: (s.chapter, s.id))
        save_slots(self.book, slots)
        self._finish_images_stage()
        return slot_id

    async def _slot_action(self, slot_id: str, doing: str, action) -> bool:
        slots = self.image_slots()
        slot = next((s for s in slots if s.id == slot_id), None)
        if slot is None:
            self.reply(f"There is no image slot {slot_id}.")
            return False
        if self._refuse_if_busy():
            return False
        self.busy = f"the Curator is {doing}"
        job = self._image_job()
        try:
            ok = await self._image_step(job, slot, action(job, slot))
        finally:
            self.busy = None
            await job.search.close()
        save_slots(self.book, slots)
        self._finish_images_stage()
        return ok

    async def _image_step(self, job, slot: ImageSlot, coroutine) -> bool:
        try:
            await coroutine
        except LLMError as error:
            self.bus.log(f"{slot.id}: {error.message}", "warning", "images", "Curator")
            return False
        return True

    def _edit_slot(self, slot_id: str, change) -> bool:
        slots = self.image_slots()
        slot = next((s for s in slots if s.id == slot_id), None)
        if slot is None:
            return False
        change(slot)
        save_slots(self.book, slots)
        self._finish_images_stage()
        return True

    def _image_job(self) -> images_stage.ImageJob:
        return images_stage.ImageJob(self.book, self.profile, self.outline, self.make_gateway(), self.models(),
                                     self.make_image_search(), self.bus)

    def _finish_images_stage(self) -> None:
        slots = self.image_slots()
        if not slots:
            self.set_stage("images", Status.IDLE)
        elif all(s.status in (SLOT_APPROVED, SLOT_SKIPPED) for s in slots):
            self.set_stage("images", Status.DONE)
        else:
            self.set_stage("images", Status.WAITING)
        self.bus.images_changed.emit()

    # ---------- Stage 6: cover ----------

    def cover(self) -> CoverSpec:
        spec = load_cover(self.book)
        if spec is None:
            outline = self.outline
            spec = CoverSpec(title=outline.title if outline else self.book.title,
                             subtitle=outline.subtitle if outline else "")
        return spec

    def cover_pages(self, spec: CoverSpec | None = None) -> int:
        spec = spec or self.cover()
        outline = self.outline
        return spec.page_count or estimate_pages(self.book, self.profile or BookProfile(),
                                                 len(outline.chapters) if outline else 0)

    async def make_cover_concepts(self) -> bool:
        """The Illuminator writes the blurb and paints 3 cover concepts (about $0.30 with 2K art)."""
        outline = self.outline
        if outline is None or not outline.approved:
            self.reply("Please approve the outline first - the cover needs the final title.")
            return False
        if self._refuse_if_busy():
            return False
        self.busy = "the Illuminator is designing covers"
        self.set_stage("cover", Status.RUNNING)
        job = cover_stage.CoverJob(self.book, self.profile, outline, self.make_gateway(step_retry=self.make_cover_concepts),
                                   self.models(), self.bus)
        try:
            spec = await cover_stage.propose(job, self.cover())
        except LLMError as error:
            self._stage_failed("cover", "Illuminator", error, retry=self.make_cover_concepts)
            return False
        finally:
            self.busy = None
        if not spec.chosen:
            first = next((c for c in spec.concepts if c.art_file), spec.concepts[0] if spec.concepts else None)
            if first:
                cover_stage.choose(spec, first.id)
        self._store_cover(spec)
        self.bus.log(f"{len(spec.concepts)} cover concepts ready - pick one in the Cover tab, add the author, "
                     "then approve.", "success", "cover", "Illuminator")
        return True

    def choose_cover_concept(self, concept_id: str) -> str:
        spec = self.cover()
        if not any(c.id == concept_id for c in spec.concepts):
            return f"There is no cover concept {concept_id}."
        cover_stage.choose(spec, concept_id)
        self._store_cover(spec)
        return f"Using cover concept {concept_id}."

    def upload_cover_art(self, side: str, path: Path) -> str:
        from PySide6.QtGui import QImageReader

        size = QImageReader(str(path)).size()
        if not size.isValid():
            return f"{path.name} is not an image the app can read."
        spec = self.cover()
        cover_stage.upload(self.book, spec, side, path)
        self._store_cover(spec)
        trim_w, _ = trim_inches(self.profile or BookProfile())
        dpi = int(size.width() / (trim_w + BLEED_IN))
        quality = "good for print" if dpi >= 300 else "a bit soft in print" if dpi >= 200 else "too small for print"
        return (f"Your {side} art is on the cover ({size.width()}×{size.height()} px ≈ {dpi} dpi - {quality}). "
                + ("If it already shows the title, tick 'Art already has the title'." if side == "front" else ""))

    def update_cover(self, spec: CoverSpec) -> None:
        self._store_cover(spec)

    def set_author(self, name: str) -> str:
        spec = self.cover()
        spec.author = name.strip()
        self._store_cover(spec)
        return f"Author set to {spec.author}."

    def approve_cover(self, spec: CoverSpec | None = None) -> str:
        spec = spec or self.cover()
        missing = [name for name, value in (("title", spec.title), ("author", spec.author)) if not value.strip()]
        if missing:
            return f"The cover needs a {' and '.join(missing)} first."
        profile = self.profile or BookProfile()
        pages = self.cover_pages(spec)
        files = export_cover(self.book, spec, profile, pages)
        spec.approved = True
        save_cover(self.book, spec)
        self.set_stage("cover", Status.DONE)
        self.bus.cover_changed.emit()
        spine = spine_width_in(pages, profile.paper)
        self.bus.log(f"Cover approved: {pages} pages, spine {spine:.3f}\" - wrote cover/wrap.pdf, wrap.png and "
                     "ebook.jpg.", "success", "cover", "You")
        return (f"Cover approved ✓ - KDP wrap for {pages} pages (spine {spine:.3f}\"), saved as {files['wrap_pdf']}. "
                "If the final page count changes, approve the cover again to resize the spine.")

    def _store_cover(self, spec: CoverSpec) -> None:
        spec.approved = False
        save_cover(self.book, spec)
        self.set_stage("cover", Status.WAITING)
        self.bus.cover_changed.emit()

    def _refuse_if_busy(self) -> bool:
        if self.busy:
            self.reply(f"Please wait - {self.busy}.")
            return True
        return False

    # ---------- reports ----------

    def status_text(self) -> str:
        stages = ", ".join(f"{STAGE_LABELS[s]}: {status}" for s, status in self.book.stages.items())
        profile = self.profile
        if profile is None:
            summary = "no profile yet"
        else:
            summary = describe(profile) + (" (approved)" if profile.approved else " (not approved)")
        return f"'{self.book.title}' - {summary}. Stages: {stages}."

    def cost_text(self) -> str:
        by_agent: dict[str, float] = defaultdict(float)
        for record in storage.read_costs(self.book):
            by_agent[record.get("agent", "?")] += float(record.get("cost_usd", 0))
        breakdown = ", ".join(f"{agent} {format_usd(cost)}" for agent, cost in sorted(by_agent.items()))
        return (f"Spent {format_usd(self.book.spent_usd)} of {format_usd(self.book.budget_usd)}"
                + (f" - {breakdown}." if breakdown else "."))

    # ---------- chat ----------

    async def handle_chat(self, text: str) -> None:
        self.bus.log(text, agent="You")
        command = quick_command(text) or await self._interpret(text)
        if command is not None:
            await self.run_command(command)

    async def run_command(self, command: Command) -> None:
        action, args = command.action, command.args
        if action == "generate_profile":
            self.reply(command.reply or "Asking the Cartographer to draft the profile…")
            await self.generate_profile()
        elif action == "revise_profile":
            self.reply(command.reply or "Asking the Cartographer to revise the profile…")
            await self.generate_profile(instruction=str(args.get("instruction", "")) or "improve it")
        elif action == "set_profile_field":
            self.reply(self.set_profile_field(str(args.get("field", "")), str(args.get("value", ""))))
        elif action == "approve_profile":
            self.reply(self.approve_profile())
        elif action == "show_status":
            self.reply(self.status_text())
        elif action == "show_cost":
            self.reply(self.cost_text())
        elif action == "run_research":
            self.reply(command.reply or "Sending out the Scouts…")
            await self.run_research()
        elif action in ("exclude_source", "include_source"):
            self.reply(self.set_source_excluded(str(args.get("source_id", "")), action == "exclude_source"))
        elif action == "run_outline":
            self.reply(command.reply or "Calling the Architects and the Council…")
            await self.run_outline()
        elif action == "revise_outline":
            self.reply(command.reply or "Asking an Architect to revise the outline…")
            await self.revise_outline(str(args.get("instruction", "")) or "improve it")
        elif action == "apply_chair_note":
            self.reply(command.reply or "Applying the Chair's note…")
            await self.apply_chair_note()
        elif action == "choose_proposal":
            try:
                index = int(args.get("index", -1))
            except (TypeError, ValueError):
                index = -1
            self.reply(self.choose_proposal(index))
        elif action == "approve_outline":
            self.reply(self.approve_outline())
        elif action == "write_chapters":
            numbers = [int(n) for n in args.get("numbers") or [] if str(n).isdigit()]
            self.reply(command.reply or "The Scribes are starting…")
            await self.write_chapters(numbers or None)
        elif action == "rewrite_chapter":
            self.reply(command.reply or "Rewriting from scratch…")
            await self.rewrite_chapter(_int(args.get("number")), str(args.get("instruction", "")))
        elif action == "revise_chapter":
            self.reply(command.reply or "A Scribe is revising the chapter…")
            await self.revise_chapter(_int(args.get("number")), str(args.get("instruction", "")) or "improve it")
        elif action == "plan_images":
            self.reply(command.reply or "The Curator is looking for images…")
            await self.plan_images()
        elif action == "generate_image":
            self.reply(command.reply or "Painting an AI illustration…")
            await self.generate_image(str(args.get("slot_id", "")))
        elif action == "skip_image":
            self.reply(self.skip_image(str(args.get("slot_id", ""))))
        elif action == "make_cover":
            self.reply(command.reply or "The Illuminator is designing covers (about a minute)…")
            await self.make_cover_concepts()
        elif action == "set_author":
            self.reply(self.set_author(str(args.get("name", ""))))
        elif action == "approve_cover":
            self.reply(self.approve_cover())
        elif action == "approve":
            self.reply(self.approve())
        elif action == "help":
            self.reply(HELP_TEXT)
        else:
            self.reply(command.reply or "I'm not sure what to do with that. " + HELP_TEXT)

    async def _interpret(self, text: str) -> Command | None:
        """Ask the Steward (a cheap model) to turn free text into a Command."""
        fields = ", ".join(k for k in BookProfile().to_dict() if k != "approved")
        prompt = prompts.render("steward", fields=fields, context=self.status_text(), message=text)
        models = self.models()
        try:
            result = await self.make_gateway().chat_json(
                agent="Steward", stage="", model=models.default, fallback_model=models.fallback,
                messages=[{"role": "user", "content": prompt}], max_tokens=1500,
                thinking="off", required_keys=("action",),
            )
        except LLMError:
            self.reply("Sorry, I couldn't reach the AI just now - see the Failures tab.")
            return None
        data = result.data if isinstance(result.data, dict) else {}
        action = data.get("action") if data.get("action") in ACTIONS else "none"
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        return Command(action, args, str(data.get("reply", "")).strip())

    def reply(self, text: str) -> None:
        self.bus.log(text, agent="Steward")
        self.bus.steward_replied.emit(text)


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def describe(profile: BookProfile) -> str:
    return (f"{profile.mode} book for {profile.audience_age}, ~{profile.target_pages} pages in "
            f"{profile.chapter_count} chapters, {profile.trim_size}, budget {format_usd(profile.budget_usd)}")
