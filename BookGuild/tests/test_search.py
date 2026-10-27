import asyncio
import json

import httpx
import pytest

from bookguild.config import Settings
from bookguild.reliability import PermanentError, TransientError
from bookguild.research.search import SearchClient, _openalex_abstract


def make_client(handler, keys: dict | None = None, monkeypatch=None) -> SearchClient:
    env = {"openrouter": "BG_TEST_OR", "tavily": "BG_TEST_TAVILY", "exa": "BG_TEST_EXA"}
    if monkeypatch:
        from bookguild import config
        monkeypatch.setattr(config, "_read_windows_registry_env", lambda env_var: None)
        for name, var in env.items():
            if keys and name in keys:
                monkeypatch.setenv(var, keys[name])
            else:
                monkeypatch.delenv(var, raising=False)
    return SearchClient(Settings(books_dir=None, key_env_vars=env), transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def test_openrouter_exa_reads_url_citations_and_splits_cost(monkeypatch):
    sent = {}

    def handler(request):
        sent["body"] = json.loads(request.read())
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok", "annotations": [
            {"type": "url_citation", "url_citation": {"url": "https://www.nobelprize.org/raman", "title": "Raman",
                                                      "content": "Raman was born in 1888."}},
            {"type": "url_citation", "url_citation": {"url": "https://example.org/b", "title": "B", "content": "x"}},
        ]}}], "usage": {"cost": 0.008}})

    client = make_client(handler, {"openrouter": "sk-or"}, monkeypatch)
    hits = run(client.search("openrouter_exa", "C. V. Raman childhood", 5))

    assert [h.url for h in hits] == ["https://www.nobelprize.org/raman", "https://example.org/b"]
    assert hits[0].text == "Raman was born in 1888." and not hits[0].full_text
    assert hits[0].cost_usd == pytest.approx(0.004)
    tool = sent["body"]["tools"][0]
    assert tool["type"] == "openrouter:web_search" and tool["parameters"]["engine"] == "exa"
    assert sent["body"]["tool_choice"] == "required"


def test_error_inside_200_body_is_raised(monkeypatch):
    client = make_client(lambda r: httpx.Response(200, json={"error": {"message": "bad tool", "code": 400}}),
                         {"openrouter": "sk-or"}, monkeypatch)
    with pytest.raises(PermanentError):
        run(client.search("openrouter_exa", "q"))


def test_tavily_marks_full_page_text(monkeypatch):
    page = "Long page text. " * 40
    body = {"results": [{"title": "T", "url": "https://a.org/x", "content": "snippet", "raw_content": page},
                        {"title": "U", "url": "https://b.org/y", "content": "only a snippet"}]}
    client = make_client(lambda r: httpx.Response(200, json=body), {"tavily": "tv"}, monkeypatch)
    hits = run(client.search("tavily", "q"))
    assert hits[0].full_text and hits[0].text.startswith("Long page text")
    assert not hits[1].full_text and hits[1].text == "only a snippet"


def test_exa_reads_cost(monkeypatch):
    body = {"results": [{"title": "T", "url": "https://a.org", "text": "x" * 400}], "costDollars": {"total": 0.005}}
    client = make_client(lambda r: httpx.Response(200, json=body), {"exa": "ex"}, monkeypatch)
    hits = run(client.search("exa", "q"))
    assert hits[0].full_text and hits[0].cost_usd == pytest.approx(0.005)


def test_missing_key_and_rate_limit(monkeypatch):
    client = make_client(lambda r: httpx.Response(429, json={}), {"tavily": "tv"}, monkeypatch)
    with pytest.raises(TransientError):
        run(client.search("tavily", "q"))
    with pytest.raises(PermanentError, match="BG_TEST_EXA is not set"):
        run(client.search("exa", "q"))
    assert client.has_key("duckduckgo") and client.has_key("tavily") and not client.has_key("exa")


def test_openalex_abstract_is_rebuilt():
    assert _openalex_abstract({"Raman": [0], "light": [3], "scattered": [2], "effect": [1]}) == \
        "Raman effect scattered light"
    assert _openalex_abstract(None) == ""


def test_scholarly_relevance_filter():
    from bookguild.research.search import SearchHit, is_relevant

    query = "CV Raman childhood early life education biography facts"
    assert is_relevant(SearchHit("Raman effect: History of the discovery", "u", "abstract", "openalex"), query)
    assert not is_relevant(SearchHit("Unveiling Rare Breast Neoplasms", "u", "diagnostic challenges", "openalex"),
                           query)
    assert is_relevant(SearchHit("Light scattering in liquids", "u", "how light scattering works", "crossref"),
                       "light scattering liquids")
