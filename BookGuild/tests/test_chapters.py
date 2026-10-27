import asyncio
import json

from bookguild import storage
from bookguild.budget import Budget
from bookguild.chapters import load_records, read_file, read_json, strip_markers, word_count
from bookguild.events import EventBus, Status
from bookguild.gateway import AIGateway
from bookguild.llm import LLMResult
from bookguild.models import load_model_profiles
from bookguild.outline import ChapterPlan, Outline, save_outline
from bookguild.profile import BookProfile, save_profile
from bookguild.reliability import PermanentError
from bookguild.research.search import SearchHit
from bookguild.session import BookSession, quick_command

MODELS = load_model_profiles()["test"]
WORDS = 250  # words per chapter in these tests (10 pages x 50 words / 2 chapters)


def chapter_text(label: str, words: int = 220) -> str:
    return f"# Chapter {label}\n\n" + " ".join(f"fact{i} [S1]." for i in range(words))


class FakeGuild:
    """Answers every agent's prompt. Scribe-2 writes the best draft; the Archivist finds one major
    problem until the text has been through a fix pass."""

    def __init__(self, failing=(), archivist_fails_once=False, short_first_draft=False):
        self.failing = set(failing)
        self.archivist_fails_once = archivist_fails_once
        self.short_first_draft = short_first_draft
        self.calls: list[str] = []

    async def chat(self, model, messages, **kwargs):
        prompt = messages[0]["content"]
        agent = prompt.split("You are ", 1)[1].split(",", 1)[0] if prompt.startswith("You are ") else "Juror"
        if agent.startswith("the Archivist"):
            agent = "Archivist"
        elif agent.startswith("the Chair"):
            agent = "Chair"
        self.calls.append(agent)
        if agent in self.failing or ("THIS CHAPTER - number 2" in prompt and "Chapter2Scribes" in self.failing
                                     and agent.startswith("Scribe")):
            raise PermanentError("refused", 403, use_fallback=False)

        if agent.startswith("Scout"):
            if '{"queries"' in prompt:
                return result(json.dumps({"queries": ["q1", "q2"]}), model)
            return result("### Facts\n- A fact [S1]", model)
        if agent.startswith("Scribe"):
            if "Fix ONLY those sentences" in prompt:
                return result(json.dumps({"edits": [{"find": "# Chapter REVISED", "replace": "# Chapter FIXED"},
                                                    {"find": "not in the chapter", "replace": ""}]}), model)
            if "Revise your chapter" in prompt:
                return result(chapter_text("REVISED"), model)
            if self.short_first_draft:
                self.short_first_draft = False
                return result("# Too short\n\nTiny.", model)
            return result(chapter_text("BEST" if agent == "Scribe-2" else agent), model)
        if agent == "Chair":
            return result(json.dumps({"note": "- tighten the ending"}), model)
        if agent == "Archivist":
            if self.archivist_fails_once:
                self.archivist_fails_once = False
                raise PermanentError("archivist down", 503, use_fallback=False)
            fixed = "Chapter FIXED" in prompt
            findings = [] if fixed else [{"quote": "fact1", "severity": "major", "problem": "not in source",
                                          "fix": "remove"}]
            return result(json.dumps({"approved": fixed, "findings": findings, "summary": "checked"}), model)
        labels = [line.split("CANDIDATE ")[1].split(" ")[0] for line in prompt.splitlines()
                  if line.startswith("===== CANDIDATE")]
        texts = prompt.split("===== CANDIDATE ")[1:]
        best = next((label for label, text in zip(labels, texts) if "BEST" in text), labels[0])
        return result(json.dumps({"scores": {label: {} for label in labels},
                                  "ranking": [best] + [label for label in labels if label != best],
                                  "reasons": {label: "ok" for label in labels}}), model)


def result(text, model):
    return LLMResult(text=text, model=model, input_tokens=10, output_tokens=10, cost_usd=0.001)


class FakeSearch:
    def has_key(self, provider):
        return True

    async def search(self, provider, query, max_results=4):
        return [SearchHit("Raman biography", f"https://www.nobelprize.org/{query}", "Raman was born in 1888.",
                          provider)]

    async def scholarly_search(self, query):
        return []

    async def fetch_text(self, url):
        return ""

    async def close(self):
        pass


def make_session(tmp_path, guild=None, budget_limit=5.0, chapters=2, approved=True):
    book = storage.create_book(tmp_path, "Legends")
    save_profile(book, BookProfile(working_title="Legends", target_pages=10, words_per_page=50,
                                   chapter_count=chapters, budget_usd=budget_limit, approved=True))
    save_outline(book, Outline("Legends", chapters=[ChapterPlan(f"Chapter {i}", "plan", ["k"], [])
                                                    for i in range(1, chapters + 1)], approved=approved))
    book.budget_usd = budget_limit
    storage.save_book(book)
    guild = guild or FakeGuild()
    bus = EventBus()

    async def no_sleep(_):
        pass

    def make_gateway(step_retry=None, cost_tag=""):
        return AIGateway(guild, bus, Budget.for_book(book), sleep=no_sleep, step_retry=step_retry, cost_tag=cost_tag)

    session = BookSession(book, bus, make_gateway, lambda: MODELS, make_search=lambda models: FakeSearch())
    replies, failures = [], []
    bus.steward_replied.connect(replies.append)
    bus.failure_added.connect(failures.append)
    return session, guild, replies, failures


def test_full_chapter_pipeline(tmp_path):
    session, guild, _, _ = make_session(tmp_path, chapters=1)
    assert asyncio.run(session.write_chapters()) is True

    record = session.chapter_records()[0]
    assert record.status == Status.DONE and record.winner == "Scribe-2"
    assert record.flags == 0 and record.words > 100
    book = session.book
    assert read_file(book, 1, "final.md").startswith("# Chapter FIXED")  # revised, then one fix pass
    report = read_json(book, 1, "factcheck.json")
    assert not report["first"]["approved"] and report["after_fix"]["approved"]
    assert read_json(book, 1, "jury.json")["chair_note"] == "- tighten the ending"
    assert len(read_json(book, 1, "drafts.json")) == 3
    assert guild.calls.count("Archivist") == 2  # one check + one re-check, never more
    assert all(c.get("item") == "ch01" for c in storage.read_costs(book))
    assert book.stages["chapters"] == Status.DONE


def test_retry_resumes_without_redrafting(tmp_path):
    guild = FakeGuild(archivist_fails_once=True)
    session, guild, _, failures = make_session(tmp_path, guild=guild, chapters=1)
    asyncio.run(session.write_chapters())
    assert session.chapter_records()[0].status == Status.FAILED
    scribe_calls = sum(c.startswith("Scribe") for c in guild.calls)

    asyncio.run(failures[-1].retry())  # the Failures panel's Retry
    assert session.chapter_records()[0].status == Status.DONE
    new_scribe_calls = sum(c.startswith("Scribe") for c in guild.calls) - scribe_calls
    assert new_scribe_calls == 1  # only the fix pass - the drafts and the revision were reused


def test_one_chapter_failing_does_not_stop_the_other(tmp_path):
    session, _, _, _ = make_session(tmp_path, guild=FakeGuild(failing={"Chapter2Scribes"}))
    asyncio.run(session.write_chapters())
    records = session.chapter_records()
    assert [r.status for r in records] == [Status.DONE, Status.FAILED]
    assert "at least 2" in records[1].error
    assert session.book.stages["chapters"] == Status.FAILED


def test_spent_budget_stops_remaining_chapters(tmp_path):
    session, _, _, _ = make_session(tmp_path, budget_limit=0.5, chapters=3)
    session.book.spent_usd = 0.5  # already used up
    storage.save_book(session.book)
    asyncio.run(session.write_chapters())
    statuses = [r.status for r in session.chapter_records()]
    assert Status.DONE not in statuses
    assert statuses.count(Status.IDLE) >= 1  # chapters after the stop were never started


def test_too_short_draft_is_retried(tmp_path):
    session, guild, _, _ = make_session(tmp_path, guild=FakeGuild(short_first_draft=True), chapters=1)
    asyncio.run(session.write_chapters())
    assert session.chapter_records()[0].status == Status.DONE
    assert len(read_json(session.book, 1, "drafts.json")) == 3


def test_rewrite_and_revise(tmp_path):
    session, guild, replies, _ = make_session(tmp_path, chapters=1)
    asyncio.run(session.write_chapters())
    assert "All chapters are written" in (asyncio.run(session.write_chapters()) or replies[-1])

    assert asyncio.run(session.revise_chapter(1, "simpler words")) is True
    assert session.chapter_records()[0].status == Status.DONE

    calls_before = len(guild.calls)
    asyncio.run(session.rewrite_chapter(1))
    assert any(c.startswith("Scout") for c in guild.calls[calls_before:])  # research was redone too


def test_chapters_need_an_approved_outline(tmp_path):
    session, _, replies, _ = make_session(tmp_path, approved=False)
    assert asyncio.run(session.write_chapters()) is False
    assert "approve the outline" in replies[-1]


def test_markers_and_word_count():
    text = "Raman was born in 1888 [S1][S4]. He loved light [NEEDS SOURCE]."
    assert strip_markers(text) == "Raman was born in 1888. He loved light."
    assert word_count(text) == 8


def test_records_follow_the_outline(tmp_path):
    session, _, _, _ = make_session(tmp_path, chapters=2)
    outline = session.outline
    outline.chapters[0].title = "Renamed"
    records = load_records(session.book, outline)
    assert [r.title for r in records] == ["Renamed", "Chapter 2"]


def test_chapter_quick_commands():
    assert quick_command("write the chapters").action == "write_chapters"
    assert quick_command("write chapter 4").args == {"numbers": [4]}
    assert quick_command("rewrite chapter 2").args == {"number": 2}


def test_surgical_fix_changes_only_flagged_sentences(tmp_path):
    session, _, _, _ = make_session(tmp_path, chapters=1)
    asyncio.run(session.write_chapters())
    book = session.book
    revised, final = read_file(book, 1, "revised.md"), read_file(book, 1, "final.md")
    assert revised.replace("# Chapter REVISED", "# Chapter FIXED") == final  # nothing else changed
    edits = read_json(book, 1, "factcheck.json")["edits"]
    assert [e["applied"] for e in edits] == [True, False]  # an edit that doesn't match is reported, not forced
