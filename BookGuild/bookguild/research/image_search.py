"""Licensed image search and downloads.

    commons   Wikimedia Commons - no key. Strict licence rules (from the author's earlier
              Great Indians project): only CC BY / CC BY-SA / CC0 / Public Domain, never
              NonCommercial / NoDerivatives / fair use; the creator must be named; no
              "Restrictions" (personality rights, trademarks…); JPEG/PNG only.
    pexels    needs PEXELS_API_KEY  - Pexels License (commercial use allowed, no attribution required)
    pixabay   needs PIXABAY_API_KEY - Pixabay Content License (same)

Unsplash is deliberately not used: its API rules require hotlinking images from Unsplash,
which a printed book can't do. Openverse was tried and timed out repeatedly.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import httpx

from bookguild.config import Settings
from bookguild.reliability import PermanentError, TransientError

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
PREVIEW_WIDTH = 600
PRINT_WIDTH = 2400  # px: enough for full width at 300 dpi on a 8.5" page; caps download size
MAX_DOWNLOAD_BYTES = 25_000_000
CC_LICENCE_PATH = re.compile(r"^/(licenses/(by|by-sa)/\d\.\d(/[a-z]{2})?(/deed\.[a-z-]+)?|publicdomain/(zero|mark)/1\.0"
                             r"(/deed\.[a-z-]+)?)/?$")
FORBIDDEN_LICENCE = re.compile(r"(?i)(non.?commercial|no.?deriv|fair.?use|all rights reserved|\bNC\b|\bND\b)")


@dataclass
class ImageHit:
    provider: str
    title: str
    preview_url: str
    full_url: str
    page_url: str
    author: str
    license: str
    license_url: str
    width: int  # of the print-size file
    height: int


class ImageSearch:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.http = httpx.AsyncClient(timeout=30, follow_redirects=True, transport=transport,
                                      headers={"User-Agent": settings.user_agent()})

    def providers(self) -> list[str]:
        return ["commons"] + [p for p in ("pexels", "pixabay") if self.settings.get_key(p)]

    async def search(self, provider: str, query: str, limit: int = 4) -> list[ImageHit]:
        if provider == "commons":
            return await self._commons(query, limit)
        if provider == "pexels":
            return await self._pexels(query, limit)
        if provider == "pixabay":
            return await self._pixabay(query, limit)
        raise PermanentError(f"Unknown image provider '{provider}'", use_fallback=False)

    async def download(self, url: str) -> bytes:
        try:
            response = await self.http.get(url, timeout=60)
        except httpx.TimeoutException:
            raise TransientError("image download timed out") from None
        except httpx.TransportError as error:
            raise TransientError(f"image download failed: {error}") from None
        if response.status_code != 200:
            raise TransientError(f"image download failed: HTTP {response.status_code}", response.status_code)
        if len(response.content) > MAX_DOWNLOAD_BYTES:
            raise PermanentError("image file is too large", use_fallback=False)
        return response.content

    async def close(self) -> None:
        await self.http.aclose()

    # ---------- providers ----------

    async def _commons(self, query: str, limit: int) -> list[ImageHit]:
        data = await self._get_json("Wikimedia Commons", COMMONS_API, {
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrsearch": query,
            "gsrlimit": limit * 3,  # many files fail the licence rules, so ask for extra
            "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": PREVIEW_WIDTH,
            "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|Restrictions|UsageTerms|ObjectName",
        })
        pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
        hits = []
        for page in pages:
            hit = commons_hit(page)
            if hit is not None:
                hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    async def _pexels(self, query: str, limit: int) -> list[ImageHit]:
        data = await self._get_json("Pexels", "https://api.pexels.com/v1/search", {"query": query, "per_page": limit},
                                    headers={"Authorization": self.settings.get_key("pexels") or ""})
        return [ImageHit("pexels", p.get("alt") or query, p["src"]["medium"], p["src"]["original"], p["url"],
                         p.get("photographer", ""), "Pexels License", "https://www.pexels.com/license/",
                         p.get("width", 0), p.get("height", 0)) for p in data.get("photos", [])]

    async def _pixabay(self, query: str, limit: int) -> list[ImageHit]:
        data = await self._get_json("Pixabay", "https://pixabay.com/api/", {
            "key": self.settings.get_key("pixabay") or "", "q": query, "per_page": max(3, limit),
            "image_type": "all", "safesearch": "true"})
        return [ImageHit("pixabay", h.get("tags", query), h["webformatURL"], h.get("largeImageURL") or
                         h["webformatURL"], h["pageURL"], h.get("user", ""), "Pixabay Content License",
                         "https://pixabay.com/service/license-summary/", h.get("imageWidth", 0),
                         h.get("imageHeight", 0)) for h in data.get("hits", [])[:limit]]

    async def _get_json(self, provider: str, url: str, params: dict, headers: dict | None = None) -> dict:
        try:
            response = await self.http.get(url, params=params, headers=headers)
        except httpx.TimeoutException:
            raise TransientError(f"{provider}: timed out") from None
        except httpx.TransportError as error:
            raise TransientError(f"{provider}: network error {error}") from None
        if response.status_code in (401, 403):
            raise PermanentError(f"{provider}: access refused ({response.text[:120]})", response.status_code)
        if response.status_code == 429 or response.status_code >= 500:
            raise TransientError(f"{provider}: error {response.status_code}", response.status_code)
        if response.status_code >= 400:
            raise PermanentError(f"{provider}: error {response.status_code}", response.status_code)
        try:
            return response.json()
        except ValueError:
            raise TransientError(f"{provider}: unreadable response") from None


def commons_hit(page: dict) -> ImageHit | None:
    """A Commons file as an ImageHit, or None if it fails any licence or format rule."""
    info = (page.get("imageinfo") or [{}])[0]
    metadata = info.get("extmetadata") or {}

    def field(name: str) -> str:
        return plain_text(str((metadata.get(name) or {}).get("value", "")))

    if info.get("mime") not in ("image/jpeg", "image/png"):
        return None
    licence, licence_url, author = field("LicenseShortName"), field("LicenseUrl"), field("Artist")
    page_url = info.get("descriptionurl", "")
    public_domain = (not licence_url and licence.lower() == "public domain"
                     and field("UsageTerms").lower() == "public domain")
    if public_domain:
        licence, licence_url = "Public domain", page_url + "#Licensing"
    elif not reusable_licence(licence, licence_url):
        return None
    if not author or field("Restrictions"):
        return None

    width, height = info.get("width", 0), info.get("height", 0)
    full_url = info.get("url", "")
    preview = info.get("thumburl") or full_url
    if width > PRINT_WIDTH and f"/{PREVIEW_WIDTH}px-" in preview:  # ask Commons for a print-size version
        full_url = preview.replace(f"/{PREVIEW_WIDTH}px-", f"/{PRINT_WIDTH}px-")
        height, width = int(height * PRINT_WIDTH / width), PRINT_WIDTH
    title = field("ObjectName") or page.get("title", "").removeprefix("File:").rsplit(".", 1)[0]
    return ImageHit("commons", title, preview, full_url, page_url, author[:200], licence, licence_url, width, height)


def reusable_licence(name: str, url: str) -> bool:
    if not url or FORBIDDEN_LICENCE.search(name):
        return False
    path = httpx.URL(url if url.startswith("http") else "https:" + url).path
    return bool(CC_LICENCE_PATH.match(path))


def plain_text(value: str) -> str:
    """Commons metadata is HTML ('<a href=…>Name</a>'): keep only the text."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())
