import asyncio
import json

import pytest

from tests.fakes import ScriptedClient

from bookguild import storage
from bookguild.budget import Budget
from bookguild.events import EventBus, Status
from bookguild.gateway import AIGateway, parse_json_reply
from bookguild.llm import LLMResult
from bookguild.reliability import (
    BudgetExceeded,
    CircuitBreaker,
    PermanentError,
    PipelinePaused,
    TransientError,
)


class Recorder:
    """Collects everything the gateway tells the bus."""

    def __init__(self, bus: EventBus):
        self.failures, self.paused, self.statuses, self.logs, self.costs = [], [], [], [], []
        bus.failure_added.connect(self.failures.append)
        bus.pipeline_paused.connect(self.paused.append)
        bus.agent_status_changed.connect(lambda a, s, d, stage: self.statuses.append((a, s)))
        bus.log_added.connect(self.logs.append)
        bus.cost_changed.connect(lambda spent, limit: self.costs.append(spent))


def make_gateway(client, budget=None, breaker=None):
    bus = EventBus()
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    gateway = AIGateway(client, bus, budget or Budget(limit_usd=5.0), breaker=breaker, sleep=fake_sleep)
    return gateway, Recorder(bus), sleeps


def chat(gateway, **overrides):
    args = dict(agent="Scout-1", stage="research", model="main/m", messages=[{"role": "user", "content": "x"}])
    args.update(overrides)
    return asyncio.run(gateway.chat(**args))


def test_success_records_cost_and_marks_agent_done(tmp_path):
    book = storage.create_book(tmp_path, "Tea")
    gateway, events, _ = make_gateway(ScriptedClient({"main/m": ["hello"]}), budget=Budget.for_book(book))

    result = chat(gateway)

    assert result.text == "hello"
    assert events.costs == [0.01]
    assert events.statuses[-1] == ("Scout-1", Status.DONE)
    assert storage.open_book(book.root).spent_usd == pytest.approx(0.01)
    cost_line = json.loads((book.folder / "costs.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert cost_line["agent"] == "Scout-1" and cost_line["model"] == "main/m"


def test_transient_error_retries_exactly_three_times_then_fails():
    client = ScriptedClient({"main/m": [TransientError("timeout")]})
    gateway, events, sleeps = make_gateway(client)

    with pytest.raises(TransientError):
        chat(gateway)

    assert len(client.calls) == 4  # 1 attempt + 3 retries
    assert sleeps == [2.0, 4.0, 8.0]
    assert events.failures[0].attempts == 4
    assert events.failures[0].kind == "transient"
    assert events.statuses[-1] == ("Scout-1", Status.FAILED)


def test_permanent_error_fails_at_once_without_fallback():
    client = ScriptedClient({"main/m": [PermanentError("bad key", 401, use_fallback=False)], "fb/m": ["ok"]})
    gateway, events, sleeps = make_gateway(client)

    with pytest.raises(PermanentError):
        chat(gateway, fallback_model="fb/m")

    assert client.calls == ["main/m"]
    assert sleeps == []
    assert events.failures[0].kind == "permanent"


def test_fallback_model_used_after_retries_run_out():
    client = ScriptedClient({"main/m": [TransientError("503")], "fb/m": ["from fallback"]})
    gateway, events, _ = make_gateway(client)

    result = chat(gateway, fallback_model="fb/m")

    assert result.text == "from fallback"
    assert client.calls == ["main/m"] * 4 + ["fb/m"]
    assert events.failures == []


def test_model_not_found_goes_straight_to_fallback():
    client = ScriptedClient({"main/m": [PermanentError("not found", 404)], "fb/m": ["ok"]})
    gateway, _, sleeps = make_gateway(client)

    assert chat(gateway, fallback_model="fb/m").text == "ok"
    assert client.calls == ["main/m", "fb/m"]
    assert sleeps == []


def test_budget_reached_blocks_the_call():
    client = ScriptedClient({"main/m": ["never"]})
    gateway, events, _ = make_gateway(client, budget=Budget(limit_usd=1.0, spent_usd=1.0))

    with pytest.raises(BudgetExceeded):
        chat(gateway)

    assert client.calls == []
    assert "Budget reached" in events.failures[0].error


def test_breaker_pauses_after_three_failed_calls_and_blocks_more():
    client = ScriptedClient({"main/m": [PermanentError("refused", 403, use_fallback=False)]})
    gateway, events, _ = make_gateway(client, breaker=CircuitBreaker(threshold=3))

    for _ in range(3):
        with pytest.raises(PermanentError):
            chat(gateway)
    assert len(events.paused) == 1

    with pytest.raises(PipelinePaused):
        chat(gateway)
    assert len(client.calls) == 3  # the 4th call never reached the client


def test_success_resets_the_breaker():
    breaker = CircuitBreaker(threshold=3)
    client = ScriptedClient({"bad/m": [PermanentError("x", 400, use_fallback=False)], "good/m": ["ok"]})
    gateway, events, _ = make_gateway(client, breaker=breaker)

    for model in ("bad/m", "bad/m", "good/m", "bad/m", "bad/m"):
        try:
            chat(gateway, model=model)
        except PermanentError:
            pass
    assert events.paused == []


def test_chat_json_retries_unreadable_json():
    client = ScriptedClient({"main/m": ["not json", '```json\n{"title": "Tea"}\n```']})
    gateway, _, sleeps = make_gateway(client)

    result = asyncio.run(gateway.chat_json(agent="Chair", stage="outline", model="main/m", messages=[]))

    assert result.data == {"title": "Tea"}
    assert sleeps == [2.0]


def test_failure_retry_runs_the_same_call_again():
    client = ScriptedClient({"main/m": [PermanentError("x", 400, use_fallback=False), "second time lucky"]})
    gateway, events, _ = make_gateway(client)

    with pytest.raises(PermanentError):
        chat(gateway)
    result = asyncio.run(events.failures[0].retry())
    assert result.text == "second time lucky"


def test_parse_json_reply():
    assert parse_json_reply('{"a": 1}') == {"a": 1}
    with pytest.raises(TransientError):
        parse_json_reply("Sure! Here you go")


def test_unusable_replies_are_still_charged(tmp_path):
    book = storage.create_book(tmp_path, "Tea")
    client = ScriptedClient({"main/m": ["not json", "{}", '{"mode": "evidence"}']})
    gateway, _, sleeps = make_gateway(client, budget=Budget.for_book(book))

    result = asyncio.run(gateway.chat_json(agent="Cartographer", stage="profile", model="main/m",
                                           messages=[], required_keys=("mode",)))

    assert result.data == {"mode": "evidence"}
    assert len(sleeps) == 2  # bad JSON, then a lazy "{}" missing "mode"
    assert storage.open_book(book.root).spent_usd == pytest.approx(0.03)  # all three attempts paid
    records = [json.loads(line) for line in (book.folder / "costs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["ok"] for r in records] == [False, False, True]


def test_parse_json_reply_required_keys():
    assert parse_json_reply('{"a": 1, "b": 2}', ("a",)) == {"a": 1, "b": 2}
    with pytest.raises(TransientError, match="missing: b"):
        parse_json_reply('{"a": 1}', ("a", "b"))
    with pytest.raises(TransientError):
        parse_json_reply("[1, 2]", ("a",))


def test_cut_off_reply_is_not_retried_with_the_same_model():
    class CutOff:
        def __init__(self):
            self.calls = []

        async def chat(self, model, messages, **kwargs):
            self.calls.append(model)
            if model == "main/m":
                return LLMResult(text='{"partial": ', model=model, cost_usd=0.01, finish_reason="length")
            return LLMResult(text='{"findings": []}', model=model, cost_usd=0.001)

    client = CutOff()
    gateway, _, sleeps = make_gateway(client)
    result = asyncio.run(gateway.chat_json(agent="Archivist", stage="chapters", model="main/m", messages=[],
                                           fallback_model="fb/m", required_keys=("findings",)))
    assert result.data == {"findings": []}
    assert client.calls == ["main/m", "fb/m"]  # no identical retries of a cut-off request
    assert sleeps == []
