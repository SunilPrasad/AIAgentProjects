import asyncio
import json

from bookguild import storage
from bookguild.budget import Budget
from bookguild.events import EventBus, Status
from bookguild.gateway import AIGateway
from bookguild.models import load_model_profiles
from bookguild.profile import load_profile
from bookguild.reliability import PermanentError
from bookguild.session import BookSession, quick_command
from tests.fakes import ScriptedClient

MODELS = load_model_profiles()["test"]
CARTOGRAPHER_REPLY = json.dumps({
    "working_title": "Leaves of Empire", "subject": "History of tea", "mode": "evidence",
    "audience_age": "adult", "target_pages": 120, "chapter_count": 12, "budget_usd": 4,
})


def make_session(tmp_path, replies: list):
    book = storage.create_book(tmp_path, "A researched history of tea for adults")
    bus = EventBus()
    client = ScriptedClient({MODELS.default: replies})

    async def no_sleep(_seconds):
        pass

    def make_gateway(step_retry=None):
        return AIGateway(client, bus, Budget.for_book(book), sleep=no_sleep, step_retry=step_retry)

    session = BookSession(book, bus, make_gateway, lambda: MODELS)
    replies_seen, failures = [], []
    bus.steward_replied.connect(replies_seen.append)
    bus.failure_added.connect(failures.append)
    return session, client, replies_seen, failures


def test_generate_profile_saves_draft_waiting_for_approval(tmp_path):
    session, client, _, _ = make_session(tmp_path, [CARTOGRAPHER_REPLY])

    profile = asyncio.run(session.generate_profile())

    assert profile.working_title == "Leaves of Empire"
    assert load_profile(session.book).target_pages == "120"
    assert session.book.stages["profile"] == Status.WAITING
    assert session.book.title == "Leaves of Empire"
    assert session.book.budget_usd == 4
    assert storage.open_book(session.book.root).stages["profile"] == Status.WAITING
    assert session.busy is None


def test_failed_generation_marks_stage_failed_and_retry_reruns_the_step(tmp_path):
    session, client, _, failures = make_session(
        tmp_path, [PermanentError("refused", 403, use_fallback=False), CARTOGRAPHER_REPLY])

    assert asyncio.run(session.generate_profile()) is None
    assert session.book.stages["profile"] == Status.FAILED
    assert session.busy is None

    asyncio.run(failures[0].retry())  # the Failures panel's Retry button
    assert session.book.stages["profile"] == Status.WAITING
    assert load_profile(session.book).working_title == "Leaves of Empire"


def test_approve_and_edit_cycle(tmp_path):
    session, _, _, _ = make_session(tmp_path, [CARTOGRAPHER_REPLY])
    assert "no profile yet" in session.approve_profile()

    asyncio.run(session.generate_profile())
    session.approve_profile()
    assert session.book.stages["profile"] == Status.DONE
    assert load_profile(session.book).approved

    message = session.set_profile_field("target_pages", "150")
    assert "150" in message
    assert load_profile(session.book).target_pages == "150"
    assert not load_profile(session.book).approved
    assert session.book.stages["profile"] == Status.WAITING
    assert "not a profile field" in session.set_profile_field("colour", "blue")


def test_busy_session_refuses_a_second_step(tmp_path):
    session, client, replies, _ = make_session(tmp_path, [CARTOGRAPHER_REPLY])
    session.busy = "the Cartographer is drafting the profile"

    assert asyncio.run(session.generate_profile()) is None
    assert client.calls == []
    assert "Please wait" in replies[-1]


def test_quick_commands_need_no_ai():
    assert quick_command("Approve!").action == "approve"
    assert quick_command("approve the profile").action == "approve_profile"
    assert quick_command("status").action == "show_status"
    assert quick_command("draft the profile").action == "generate_profile"
    cmd = quick_command("set target_pages to 120")
    assert (cmd.action, cmd.args) == ("set_profile_field", {"field": "target_pages", "value": "120"})
    assert quick_command("make it for teenagers please") is None


def test_free_text_goes_through_the_steward_then_the_cartographer(tmp_path):
    steward = json.dumps({"action": "revise_profile", "args": {"instruction": "make it for teenagers"},
                          "reply": "On it!"})
    revised = json.dumps({"working_title": "Tea for Teens", "mode": "evidence", "audience_age": "13-17",
                          "target_pages": 80, "chapter_count": 8})
    session, client, replies, _ = make_session(tmp_path, [CARTOGRAPHER_REPLY, steward, revised])

    asyncio.run(session.generate_profile())
    asyncio.run(session.handle_chat("make it for teenagers please"))

    assert replies[0] == "On it!"
    assert load_profile(session.book).audience_age == "13-17"
    assert len(client.calls) == 3  # cartographer, steward, cartographer


def test_cost_and_status_reports(tmp_path):
    session, _, replies, _ = make_session(tmp_path, [CARTOGRAPHER_REPLY])
    asyncio.run(session.generate_profile())

    asyncio.run(session.handle_chat("cost"))
    assert "Cartographer $0.01." in replies[-1]
    asyncio.run(session.handle_chat("status"))
    assert "Profile: waiting" in replies[-1]
