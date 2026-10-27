"""Model profiles: which OpenRouter model each Guild role uses, and which web search
provider the Scouts use (config/models.toml).

Also enforces provider diversity, so the jury never shares a "brain" with the writers.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from bookguild.config import PROJECT_ROOT

DEFAULT_MODELS_PATH = PROJECT_ROOT / "config" / "models.toml"
PROFILE_NAMES = ("test", "balanced", "quality")
MIN_DRAFTS, MAX_DRAFTS = 2, 5


@dataclass(frozen=True)
class SearchProvider:
    id: str
    label: str
    key_name: str | None  # logical key name in settings.toml [keys], or None if no key is needed
    cost_note: str


# Web search providers the Scouts can use (research/search.py).
SEARCH_PROVIDERS: dict[str, SearchProvider] = {
    p.id: p
    for p in (
        SearchProvider("openrouter_exa", "Exa via OpenRouter", "openrouter",
                       "Good sources with page excerpts, using your OpenRouter key and credits. About $0.007 per search."),
        SearchProvider("duckduckgo", "DuckDuckGo", None,
                       "Free, no key. Basic results - for testing only, not for evidence books."),
        SearchProvider("tavily", "Tavily", "tavily",
                       "Built for AI research, returns page text. Free monthly allowance, then paid."),
        SearchProvider("exa", "Exa", "exa",
                       "Semantic search built for research, returns page text. Paid per search."),
    )
}

# Free sources the Scouts always add for evidence books. (Semantic Scholar was dropped:
# it refuses requests without an API key. The OpenRouter web plugin returned no sources.)
SCHOLARLY_SOURCES = ("Wikipedia", "OpenAlex", "Crossref")


@dataclass
class ModelProfile:
    name: str
    default: str
    scribes: list[str]
    jurors: list[str]
    chair: str
    archivist: str
    image: str
    fallback: str
    cover_image: str = "google/gemini-3.1-flash-image"  # needs 2K output: ~1696x2528 px ≈ 277 dpi on a 6x9 cover
    search: str = "duckduckgo"  # primary web search provider for the Scouts
    search_fallback: str = "duckduckgo"  # used if the primary fails or has no key
    extra: dict = field(default_factory=dict)  # unknown keys are kept when saving

    def model_for(self, agent: str) -> str:
        """The model a named Guild agent uses, e.g. 'Scribe-2' -> scribes[1]."""
        group, index = _split_agent_name(agent)
        if group in ("Scribe", "Architect") and index is not None and index < len(self.scribes):
            return self.scribes[index]
        if group == "Juror" and index is not None and index < len(self.jurors):
            return self.jurors[index]
        if agent == "Chair":
            return self.chair
        if agent == "Archivist":
            return self.archivist
        return self.default


def provider_of(model_id: str) -> str:
    return model_id.split("/", 1)[0].strip().lower()


def diversity_problems(profile: ModelProfile) -> list[str]:
    """Human-readable rule violations. An empty list means the profile is OK."""
    problems = []
    if not MIN_DRAFTS <= len(profile.scribes) <= MAX_DRAFTS:
        problems.append(f"Need {MIN_DRAFTS}-{MAX_DRAFTS} Scribes, found {len(profile.scribes)}.")

    scribe_providers = [provider_of(m) for m in profile.scribes]
    for provider in sorted({p for p in scribe_providers if scribe_providers.count(p) > 1}):
        problems.append(f"Two Scribes use the same provider '{provider}' - drafts would be too similar.")

    juror_providers = [provider_of(m) for m in profile.jurors]
    for provider in sorted({p for p in juror_providers if juror_providers.count(p) > 1}):
        problems.append(f"Two jurors use the same provider '{provider}'.")

    council = profile.jurors + [profile.chair]
    for model in council:
        if provider_of(model) in scribe_providers:
            problems.append(f"Council model '{model}' shares provider '{provider_of(model)}' with a Scribe.")

    for search in (profile.search, profile.search_fallback):
        if search not in SEARCH_PROVIDERS:
            problems.append(f"Unknown web search provider '{search}'.")
    return problems


def load_model_profiles(path: Path = DEFAULT_MODELS_PATH) -> dict[str, ModelProfile]:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    profiles = {}
    for name, values in data.get("profiles", {}).items():
        values = dict(values)
        profiles[name] = ModelProfile(
            name=name,
            default=values.pop("default"),
            scribes=list(values.pop("scribes")),
            jurors=list(values.pop("jurors")),
            chair=values.pop("chair"),
            archivist=values.pop("archivist"),
            image=values.pop("image"),
            fallback=values.pop("fallback"),
            cover_image=values.pop("cover_image", "google/gemini-3.1-flash-image"),
            search=values.pop("search", "duckduckgo"),
            search_fallback=values.pop("search_fallback", "duckduckgo"),
            extra=values,
        )
    return profiles


def save_model_profiles(profiles: dict[str, ModelProfile], path: Path = DEFAULT_MODELS_PATH) -> None:
    lines = [
        "# Which OpenRouter model each Guild role uses, per profile.",
        "# Edit here or via AI > Models... in the app.",
        "# Rules: each Scribe uses a different provider; the Council (jurors + chair)",
        "# uses no provider that any Scribe uses.",
        f"# Web search providers: {', '.join(SEARCH_PROVIDERS)}",
    ]
    for profile in profiles.values():
        lines += [
            "",
            f"[profiles.{profile.name}]",
            f"default   = {json.dumps(profile.default)}",
            f"scribes   = {json.dumps(profile.scribes)}",
            f"jurors    = {json.dumps(profile.jurors)}",
            f"chair     = {json.dumps(profile.chair)}",
            f"archivist = {json.dumps(profile.archivist)}",
            f"image     = {json.dumps(profile.image)}",
            f"cover_image = {json.dumps(profile.cover_image)}",
            f"fallback  = {json.dumps(profile.fallback)}",
            f"search          = {json.dumps(profile.search)}",
            f"search_fallback = {json.dumps(profile.search_fallback)}",
        ]
        lines += [f"{key} = {json.dumps(value)}" for key, value in profile.extra.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _split_agent_name(agent: str) -> tuple[str, int | None]:
    match = re.fullmatch(r"(\w+)-(\d+)", agent)
    if not match:
        return agent, None
    return match.group(1), int(match.group(2)) - 1
