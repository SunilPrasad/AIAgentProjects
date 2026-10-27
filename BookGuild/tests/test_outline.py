import asyncio
import json

from bookguild import storage
from bookguild.budget import Budget
from bookguild.events import EventBus, Status
from bookguild.gateway import AIGateway
from bookguild.llm import LLMResult
from bookguild.models import load_model_profiles
from bookguild.outline import Outline, load_outline, load_proposals, load_verdict
from bookguild.profile import BookProfile, save_profile
from bookguild.reliability import PermanentError
from bookguild.session import BookSession, quick_command

MODELS = load_model_profiles()["test"]


def outline_json(title, chapters=3, best=False):
    return json.dumps({"title": title + (" BEST" if best else ""), "subtitle": "sub", "pitch": "pitch",
                       "chapters": [{"title": f"Chapter {i}", "summary": "s", "key_points": ["k"], "sources": ["s1"]}
                                    for i in range(1, chapters + 1)]})


class FakeGuild:
    """Architects return outlines (Architect-2's is the best), jurors vote for 'BEST', the Chair writes a note."""

    def __init__(self, failing_architects=()):
        self.failing = set(failing_architects)

    async def chat(self, model, messages, **kwargs):
        prompt = messages[0]["content"]
        if prompt.startswith("You are Architect-"):
            name = prompt.split("You are ", 1)[1].split(",", 1)[0]
            if name in self.failing:
                raise PermanentError("refused", 403, use_fallback=False)
            if "Revise the book outline" in prompt:
                return LLMResult(text=outline_json("Revised", chapters=4), model=model)
            return LLMResult(text=outline_json(f"By {name}", best=name == "Architect-2"), model=model)
        if prompt.startswith("You are the Chair"):
            return LLMResult(text=json.dumps({"note": "- add a chapter on Janaki Ammal"}), model=model)
        labels = [line.split("CANDIDATE ")[1].split(" ")[0] for line in prompt.splitlines()
                  if line.startswith("===== CANDIDATE")]
        texts = prompt.split("===== CANDIDATE ")[1:]
        best = next(label for label, text in zip(labels, texts) if "BEST" in text)
        return LLMResult(text=json.dumps({
            "scores": {label: {} for label in labels},
            "ranking": [best] + [label for label in labels if label != best],
            "reasons": {label: "clear" for label in labels}}), model=model)


def make_session(tmp_path, ai=None, research_done=True):
    book = storage.create_book(tmp_path, "Legends of Modern Indian Science")
    save_profile(book, BookProfile(working_title="Legends", chapter_count=3, approved=True))
    if research_done:
        book.stages["research"] = Status.DONE
        storage.save_book(book)
    bus = EventBus()

    async def no_sleep(_):
        pass

    def make_gateway(step_retry=None):
        return AIGateway(ai or FakeGuild(), bus, Budget.for_book(book), sleep=no_sleep, step_retry=step_retry)

    session = BookSession(book, bus, make_gateway, lambda: MODELS)
    replies, failures = [], []
    bus.steward_replied.connect(replies.append)
    bus.failure_added.connect(failures.append)
    return session, replies, failures


def test_architects_propose_and_council_picks(tmp_path):
    session, _, _ = make_session(tmp_path)
    assert asyncio.run(session.run_outline()) is True

    proposals = load_proposals(session.book)
    assert [p.architect for p in proposals] == ["Architect-1", "Architect-2", "Architect-3"]
    verdict = load_verdict(session.book)
    assert verdict["winner"] == 1 and verdict["chair_note"]
    outline = load_outline(session.book)
    assert outline.title == "By Architect-2 BEST" and not outline.approved
    assert outline.chapters[0].sources == ["S1"]
    assert session.book.stages["outline"] == Status.WAITING


def test_outline_needs_research_first(tmp_path):
    session, replies, _ = make_session(tmp_path, research_done=False)
    assert asyncio.run(session.run_outline()) is False
    assert "research" in replies[-1]


def test_one_failed_architect_is_fine_two_is_a_failure(tmp_path):
    session, _, _ = make_session(tmp_path, ai=FakeGuild(failing_architects={"Architect-1"}))
    assert asyncio.run(session.run_outline()) is True
    assert len(load_proposals(session.book)) == 2

    session2, _, failures = make_session(tmp_path / "b", ai=FakeGuild(failing_architects={"Architect-1",
                                                                                          "Architect-3"}))
    assert asyncio.run(session2.run_outline()) is False
    assert session2.book.stages["outline"] == Status.FAILED
    assert any("at least 2 are needed" in f.error for f in failures)


def test_apply_note_choose_edit_and_approve(tmp_path):
    session, _, _ = make_session(tmp_path)
    asyncio.run(session.run_outline())

    assert asyncio.run(session.apply_chair_note()) is True
    assert load_outline(session.book).title == "Revised"

    assert "proposal A" in session.choose_proposal(0)
    assert load_outline(session.book).title == "By Architect-1"
    assert "no proposal" in session.choose_proposal(7)

    assert "Outline approved" in session.approve()  # profile is approved, so 'approve' means the outline
    assert session.book.stages["outline"] == Status.DONE
    assert session.book.title == "By Architect-1"

    edited = load_outline(session.book)
    edited.chapters.pop()
    session.save_outline(edited)
    assert session.book.stages["outline"] == Status.WAITING and not load_outline(session.book).approved


def test_outline_from_dict_cleans_input():
    outline, warnings = Outline.from_dict({"title": "  T  ", "chapters": ["Just a title", {"summary": "no title"},
                                                                           {"title": "C", "sources": "s4"}]})
    assert outline.title == "T"
    assert [c.title for c in outline.chapters] == ["Just a title", "C"]
    assert outline.chapters[1].sources == ["S4"]
    assert len(warnings) == 1


def test_outline_quick_commands():
    assert quick_command("make the outline").action == "run_outline"
    assert quick_command("apply the chair's note").action == "apply_chair_note"
    assert quick_command("use proposal C").args == {"index": 2}
    assert quick_command("approve outline").action == "approve_outline"
