"""Search providers. Each method makes ONE search (or one small group of requests) and
returns SearchHits; retries and fallbacks are decided by the research stage.

Web search (one is chosen per model profile):
    openrouter_exa  Exa search run by OpenRouter (the `openrouter:web_search` tool) - uses your
                    OpenRouter key, returns good sources with excerpts, ~$0.007 per search.
                    (This approach came from the author's earlier Great Indians project.)
    duckduckgo  free, no key; returns snippets only, so pages are fetched and read separately
    tavily      returns page text; needs TAVILY_API_KEY
    exa         returns page text and its cost; needs EXA_API_KEY

Always-on free sources for evidence books (scholarly_search):
    Wikipedia, OpenAlex (papers with abstracts), Crossref (papers with abstracts)
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import httpx

from bookguild.config import Settings
from bookguild.reliability import PermanentError, TransientError

MAX_TEXT_CHARS = 6000  # text kept per source - enough for the Scouts, small enough to stay cheap
MIN_PAGE_TEXT = 300  # fetched pages shorter than this are treated as unreadable


@dataclass
class SearchHit:
    title: str
    url: str
    text: str  # page text when available, otherwise the search snippet
    provider: str
    full_text: bool = False  # True when `text` is the page itself, not just a snippet
    scholarly: bool = False
    cost_usd: float = 0.0


class SearchClient:
    def __init__(self, settings: Settings, search_model: str = "qwen/qwen3.7-flash",
                 transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.search_model = search_model  # cheap model that runs OpenRouter's web search tool
        self.http = httpx.AsyncClient(timeout=30, follow_redirects=True, transport=transport,
                                      headers={"User-Agent": settings.user_agent()})

    def has_key(self, provider: str) -> bool:
        key_name = {"duckduckgo": None, "openrouter_exa": "openrouter"}.get(provider, provider)
        return key_name is None or self.settings.get_key(key_name) is not None

    async def search(self, provider: str, query: str, max_results: int = 4) -> list[SearchHit]:
        if provider == "openrouter_exa":
            return await self._openrouter_exa(query, max_results)
        if provider == "duckduckgo":
            return await self._duckduckgo(query, max_results)
        if provider == "tavily":
            return await self._tavily(query, max_results)
        if provider == "exa":
            return await self._exa(query, max_results)
        raise PermanentError(f"Unknown search provider '{provider}'", use_fallback=True)

    async def scholarly_search(self, query: str) -> list[SearchHit]:
        """Wikipedia + OpenAlex + Crossref. A source that fails is skipped (they are a bonus).

        Their keyword search often returns unrelated papers for long queries (in testing, a query
        about C. V. Raman returned papers on breast tumours), so off-topic hits are dropped.
        """
        results = await asyncio.gather(self._wikipedia(query), self._openalex(query), self._crossref(query),
                                       return_exceptions=True)
        hits = [hit for result in results if isinstance(result, list) for hit in result]
        return [hit for hit in hits if is_relevant(hit, query)]

    async def fetch_text(self, url: str) -> str:
        """Readable main text of a web page, or "" if it can't be read (blocked, needs JavaScript, PDF…)."""
        import trafilatura

        try:
            response = await self.http.get(url, timeout=15)
            if response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
                return ""
            text = await asyncio.to_thread(trafilatura.extract, response.text) or ""
        except (httpx.HTTPError, ValueError):
            return ""
        return text[:MAX_TEXT_CHARS] if len(text) >= MIN_PAGE_TEXT else ""

    async def close(self) -> None:
        await self.http.aclose()

    # ---------- web search providers ----------

    async def _openrouter_exa(self, query: str, max_results: int) -> list[SearchHit]:
        """OpenRouter's server-side web search tool with the Exa engine. The model only triggers the
        search; the sources come back as `url_citation` annotations with page excerpts."""
        data = await self._post_json(
            "OpenRouter web search", "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._key('openrouter')}"},
            payload={
                "model": self.search_model, "max_tokens": 300, "usage": {"include": True},
                "reasoning": {"enabled": False}, "tool_choice": "required",
                "tools": [{"type": "openrouter:web_search",
                           "parameters": {"engine": "exa", "max_results": max_results, "max_uses": 1}}],
                "messages": [{"role": "user", "content": f"Search the web for: {query}\nReply with one short sentence."}],
            })
        try:
            annotations = data["choices"][0]["message"].get("annotations") or []
        except (KeyError, IndexError, TypeError):
            raise TransientError("OpenRouter web search: response had no message") from None
        citations = [a["url_citation"] for a in annotations if a.get("type") == "url_citation"]
        cost = float((data.get("usage") or {}).get("cost") or 0.0)
        return [SearchHit(title=c.get("title") or c["url"], url=c["url"], text=(c.get("content") or "")[:MAX_TEXT_CHARS],
                          provider="openrouter_exa", cost_usd=cost / max(1, len(citations)))
                for c in citations if c.get("url")]

    async def _duckduckgo(self, query: str, max_results: int) -> list[SearchHit]:
        from ddgs import DDGS
        from ddgs.exceptions import DDGSException

        try:
            rows = await asyncio.to_thread(lambda: DDGS().text(query, max_results=max_results))
        except DDGSException as error:
            raise TransientError(f"DuckDuckGo: {error}") from None
        return [SearchHit(title=r.get("title", ""), url=r.get("href", ""), text=r.get("body", ""),
                          provider="duckduckgo") for r in rows if r.get("href")]

    async def _tavily(self, query: str, max_results: int) -> list[SearchHit]:
        data = await self._post_json("tavily", "https://api.tavily.com/search",
                                     headers={"Authorization": f"Bearer {self._key('tavily')}"},
                                     payload={"query": query, "search_depth": "advanced",
                                              "max_results": max_results, "include_raw_content": True})
        hits = []
        for r in data.get("results", []):
            page = r.get("raw_content") or ""
            hits.append(SearchHit(title=r.get("title", ""), url=r.get("url", ""), provider="tavily",
                                  text=(page or r.get("content", ""))[:MAX_TEXT_CHARS],
                                  full_text=len(page) >= MIN_PAGE_TEXT))
        return hits

    async def _exa(self, query: str, max_results: int) -> list[SearchHit]:
        data = await self._post_json("exa", "https://api.exa.ai/search",
                                     headers={"x-api-key": self._key("exa")},
                                     payload={"query": query, "numResults": max_results,
                                              "contents": {"text": {"maxCharacters": MAX_TEXT_CHARS}}})
        results = data.get("results", [])
        cost = float((data.get("costDollars") or {}).get("total") or 0.0)
        return [SearchHit(title=r.get("title") or "", url=r.get("url", ""), text=r.get("text") or "",
                          provider="exa", full_text=len(r.get("text") or "") >= MIN_PAGE_TEXT,
                          cost_usd=cost / max(1, len(results)))
                for r in results]

    # ---------- free scholarly sources ----------

    async def _wikipedia(self, query: str, max_results: int = 2) -> list[SearchHit]:
        api = "https://en.wikipedia.org/w/api.php"
        found = await self._get_json("Wikipedia", api, {"action": "query", "list": "search", "srsearch": query,
                                                        "format": "json", "srlimit": max_results})
        hits = []
        for item in found.get("query", {}).get("search", []):
            title = item["title"]
            page = await self._get_json("Wikipedia", api, {"action": "query", "prop": "extracts", "explaintext": 1,
                                                           "titles": title, "format": "json", "redirects": 1})
            text = next(iter(page.get("query", {}).get("pages", {}).values()), {}).get("extract", "")
            hits.append(SearchHit(title=f"{title} - Wikipedia", provider="wikipedia", full_text=True,
                                  url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                                  text=text[:MAX_TEXT_CHARS]))
        return hits

    async def _openalex(self, query: str, max_results: int = 3) -> list[SearchHit]:
        data = await self._get_json("OpenAlex", "https://api.openalex.org/works",
                                    {"search": query, "per-page": max_results})
        hits = []
        for work in data.get("results", []):
            abstract = _openalex_abstract(work.get("abstract_inverted_index"))
            if not abstract:
                continue
            venue = ((work.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
            text = f"{work.get('display_name', '')} ({work.get('publication_year', '')}, {venue}).\n{abstract}"
            hits.append(SearchHit(title=work.get("display_name", ""), url=work.get("doi") or work.get("id", ""),
                                  text=text[:MAX_TEXT_CHARS], provider="openalex", scholarly=True))
        return hits

    async def _crossref(self, query: str, max_results: int = 3) -> list[SearchHit]:
        data = await self._get_json("Crossref", "https://api.crossref.org/works", {"query": query, "rows": max_results})
        hits = []
        for item in data.get("message", {}).get("items", []):
            abstract = re.sub(r"<[^>]+>", " ", item.get("abstract", "")).strip()
            if not abstract:
                continue
            title = (item.get("title") or [""])[0]
            year = ((item.get("issued") or {}).get("date-parts") or [[""]])[0][0]
            hits.append(SearchHit(title=title, url=f"https://doi.org/{item['DOI']}", provider="crossref",
                                  text=f"{title} ({year}).\n{abstract}"[:MAX_TEXT_CHARS], scholarly=True))
        return hits

    # ---------- HTTP helpers ----------

    def _key(self, provider: str) -> str:
        key = self.settings.get_key(provider)
        if not key:
            env_var = self.settings.key_env_vars.get(provider, provider)
            raise PermanentError(f"{provider}: no API key ({env_var} is not set)", use_fallback=True)
        return key

    async def _post_json(self, provider: str, url: str, headers: dict, payload: dict) -> dict:
        try:
            response = await self.http.post(url, headers=headers, json=payload)
        except httpx.TimeoutException:
            raise TransientError(f"{provider}: timed out") from None
        except httpx.TransportError as error:
            raise TransientError(f"{provider}: network error {error}") from None
        return _checked_json(provider, response)

    async def _get_json(self, provider: str, url: str, params: dict) -> dict:
        try:
            response = await self.http.get(url, params=params)
        except httpx.TimeoutException:
            raise TransientError(f"{provider}: timed out") from None
        except httpx.TransportError as error:
            raise TransientError(f"{provider}: network error {error}") from None
        return _checked_json(provider, response)


STOP_WORDS = {"history", "biography", "facts", "story", "stories", "early", "life", "simple", "explained",
              "explanation", "lesser", "known", "verified", "museum", "archives", "children", "about", "with",
              "from", "their", "what", "when", "where", "which", "role", "contributions", "discovery",
              "india", "indian", "ancient", "modern", "world", "national"}  # too common to show relevance


def is_relevant(hit: SearchHit, query: str) -> bool:
    """Does the hit talk about what the query is about?

    If the query names people or things (capitalised words such as "Raman" or "Bhabha"), the hit
    must mention at least one of them. Otherwise it must share at least two meaningful words.
    """
    haystack = f"{hit.title} {hit.text}".lower()
    names = {w.lower() for w in re.findall(r"\b[A-Z][A-Za-z]{2,}\b", query)} - STOP_WORDS
    if names:
        return any(name in haystack for name in names)
    words = {w for w in re.findall(r"[a-z]{4,}", query.lower())} - STOP_WORDS
    return sum(1 for w in words if w in haystack) >= min(2, len(words))


def _checked_json(provider: str, response: httpx.Response) -> dict:
    status = response.status_code
    if status in (401, 403):
        raise PermanentError(f"{provider}: access refused (check the API key)", status)
    if status == 429 or status >= 500:
        raise TransientError(f"{provider}: error {status}", status)
    if status >= 400:
        raise PermanentError(f"{provider}: error {status} {response.text[:150]}", status)
    try:
        data = response.json()
    except ValueError:
        raise TransientError(f"{provider}: unreadable response") from None
    if not isinstance(data, dict):
        raise TransientError(f"{provider}: unexpected response")
    error = data.get("error")
    if isinstance(error, dict):  # OpenRouter can report errors inside a 200 response
        code = error.get("code") if isinstance(error.get("code"), int) else 502
        error_type = TransientError if code == 429 or code >= 500 else PermanentError
        raise error_type(f"{provider}: {error.get('message', 'error')}", code)
    return data


def _openalex_abstract(inverted_index: dict | None) -> str:
    """OpenAlex stores abstracts as {word: [positions]}; rebuild the text."""
    if not inverted_index:
        return ""
    positions = [(pos, word) for word, places in inverted_index.items() for pos in places]
    return " ".join(word for _, word in sorted(positions))

