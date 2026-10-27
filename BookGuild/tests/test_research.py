import asyncio
import json

from bookguild import storage
from bookguild.budget import Budget
from bookguild.events import EventBus, Status
from bookguild.gateway import AIGateway
from bookguild.llm import LLMResult
from bookguild.models import load_model_profiles
from bookguild.profile import BookProfile, save_profile
from bookguild.reliability import PermanentError, TransientError
from bookguild.research.search import SearchHit
from bookguild.research.sources import load_sources
from bookguild.session import BookSession, quick_command
from bookguild.stages import research

MODELS = load_model_profiles()["test"]


class FakeAI:
    """Answers Scout prompts: query planning gets JSON, note writing gets cited bullets."""

    def __init__(self, failing_scout: str | None = None):
        self.failing_scout = failing_scout

    async def chat(self, model, messages, **kwargs):
        prompt = messages[0]["content"]
        scout = prompt.split("You are ", 1)[1].split(",", 1)[0]
        if scout == self.failing_scout:
            raise PermanentError("refused", 403, use_fallback=False)
        if '{"queries"' in prompt:
            text = json.dumps({"queries": [f"{scout} query {i}" for i in range(1, 5)]})
        else:
            text = f"### Facts\n- A fact from {scout} [S1]\n- Another fact [S2]\n### Gaps\n- none"
        return LLMResult(text=text, model=model, input_tokens=10, output_tokens=10, cost_usd=0.001)


class FakeSearch:
    def __init__(self, keys=("duckduckgo", "openrouter_exa"), broken=()):
        self.keys, self.broken, self.searched = keys, broken, []

    def has_key(self, provider):
        return provider in self.keys

    async def search(self, provider, query, max_results=4):
        self.searched.append(provider)
        if provider in self.broken:
            raise TransientError(f"{provider} is down")
        n = query.split()[-1]
        return [SearchHit(f"Page {n}", f"https://site{n}.org/{provider}", "snippet", provider, cost_usd=0.002),
                SearchHit("Pin", "https://pinterest.com/x", "", provider)]

    async def scholarly_search(self, query):
        return [SearchHit("Paper", "https://doi.org/10.1/p", "abstract", "openalex", scholarly=True)]

    async def fetch_text(self, url):
        return "Readable page text. " * 30

    async def close(self):
        pass


def make_job(tmp_path, ai=None, search=None):
    book = storage.create_book(tmp_path, "Legends of Modern Indian Science")
    profile = BookProfile(working_title="Legends", mode="evidence", approved=True)
    save_profile(book, profile)
    bus = EventBus()

    async def no_sleep(_):
        pass

    gateway = AIGateway(ai or FakeAI(), bus, Budget.for_book(book), sleep=no_sleep)
    job = research.ResearchJob(book, profile, gateway, MODELS, search or FakeSearch(), bus, sleep=no_sleep)
    return job, bus


def test_three_scouts_produce_sources_notes_and_brief(tmp_path):
    job, _ = make_job(tmp_path)
    reports, errors = asyncio.run(research.run(job))

    assert len(reports) == 3 and errors == []
    sources = load_sources(job.book)
    assert sources and all("pinterest" not in s.url for s in sources)
    assert any(s.quality == 90 for s in sources)  # the scholarly paper
    assert all(s.full_text for s in sources if s.provider == "openrouter_exa")  # pages were read
    brief = research.read_topic_brief(job.book)
    assert "## Scout-1: Core facts" in brief and "## Scout-3: Human details" in brief and "## Sources" in brief
    assert (job.book.folder / "research/notes-scout-2.md").exists()
    searches = [c for c in storage.read_costs(job.book) if c["model"] == "search:openrouter_exa"]
    assert len(searches) == 12  # 3 Scouts x 4 queries, each logged with its cost


def test_one_failing_scout_does_not_stop_the_others(tmp_path):
    job, _ = make_job(tmp_path, ai=FakeAI(failing_scout="Scout-2"))
    reports, errors = asyncio.run(research.run(job))

    assert [r.scout for r in reports] == ["Scout-1", "Scout-3"]
    assert len(errors) == 1 and errors[0].startswith("Scout-2")
    assert "## Scout-2" not in research.read_topic_brief(job.book)


def test_broken_primary_search_falls_back(tmp_path):
    search = FakeSearch(broken=("openrouter_exa",))
    job, _ = make_job(tmp_path, search=search)
    reports, _ = asyncio.run(research.run(job))

    assert len(reports) == 3
    assert "duckduckgo" in search.searched
    assert search.searched.count("openrouter_exa") == 12 * 4  # each query: 1 try + 3 retries, then fallback


def test_missing_key_skips_straight_to_fallback(tmp_path):
    search = FakeSearch(keys=("duckduckgo",))
    job, _ = make_job(tmp_path, search=search)
    asyncio.run(research.run(job))
    assert set(search.searched) == {"duckduckgo"}


def make_session(tmp_path, approved=True, ai=None):
    job, bus = make_job(tmp_path, ai=ai)
    save_profile(job.book, BookProfile(working_title="Legends", mode="evidence", approved=approved))

    def make_gateway(step_retry=None):
        return AIGateway(ai or FakeAI(), bus, Budget.for_book(job.book), step_retry=step_retry,
                         sleep=job.sleep)

    session = BookSession(job.book, bus, make_gateway, lambda: MODELS, make_search=lambda models: FakeSearch())
    replies = []
    bus.steward_replied.connect(replies.append)
    return session, replies


def test_session_research_requires_approved_profile(tmp_path):
    session, replies = make_session(tmp_path, approved=False)
    assert asyncio.run(session.run_research()) is False
    assert "approve the Book Profile" in replies[-1]
    assert session.book.stages["research"] == Status.IDLE


def test_session_research_and_exclusion(tmp_path):
    session, _ = make_session(tmp_path)
    assert asyncio.run(session.run_research()) is True
    assert session.book.stages["research"] == Status.DONE

    message = session.set_source_excluded("S1", True)
    assert message.startswith("Excluded S1")
    assert load_sources(session.book)[0].excluded
    brief = research.read_topic_brief(session.book)
    assert "A fact from" not in brief  # those notes cited only S1
    assert "Another fact [S2]" in brief
    assert "excluded by you" in brief
    assert "no source S99" in session.set_source_excluded("S99", True)


def test_all_scouts_failing_marks_research_failed(tmp_path):
    class AlwaysFails(FakeAI):
        async def chat(self, model, messages, **kwargs):
            raise PermanentError("refused", 403, use_fallback=False)

    session, _ = make_session(tmp_path, ai=AlwaysFails())
    assert asyncio.run(session.run_research()) is False
    assert session.book.stages["research"] == Status.FAILED
    assert session.busy is None


def test_research_quick_commands():
    assert quick_command("run research").action == "run_research"
    assert quick_command("Research").action == "run_research"
    cmd = quick_command("exclude S4")
    assert (cmd.action, cmd.args) == ("exclude_source", {"source_id": "S4"})
    assert quick_command("include source s12").args == {"source_id": "S12"}
