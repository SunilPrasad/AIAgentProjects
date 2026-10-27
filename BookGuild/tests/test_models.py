import copy

import pytest

from bookguild.models import (
    diversity_problems,
    load_model_profiles,
    provider_of,
    save_model_profiles,
)


@pytest.fixture
def profiles():
    return load_model_profiles()


def test_shipped_profiles_exist_and_follow_the_rules(profiles):
    assert set(profiles) == {"test", "balanced", "quality"}
    for profile in profiles.values():
        assert diversity_problems(profile) == [], profile.name


def test_model_for_agent(profiles):
    p = profiles["test"]
    assert p.model_for("Scribe-2") == p.scribes[1]
    assert p.model_for("Architect-1") == p.scribes[0]
    assert p.model_for("Juror-3") == p.jurors[2]
    assert p.model_for("Chair") == p.chair
    assert p.model_for("Archivist") == p.archivist
    assert p.model_for("Scout-1") == p.default
    assert p.model_for("Steward") == p.default


def test_same_provider_scribes_are_rejected(profiles):
    p = copy.deepcopy(profiles["test"])
    p.scribes = ["deepseek/a", "deepseek/b", "qwen/c"]
    assert any("same provider 'deepseek'" in problem for problem in diversity_problems(p))


def test_council_sharing_provider_with_scribe_is_rejected(profiles):
    p = copy.deepcopy(profiles["test"])
    p.chair = p.scribes[0].split("/")[0] + "/some-model"
    assert any("Council model" in problem for problem in diversity_problems(p))


def test_draft_count_limits(profiles):
    p = copy.deepcopy(profiles["test"])
    p.scribes = ["a/1"]
    assert any("Need 2-5 Scribes" in problem for problem in diversity_problems(p))


def test_save_and_load_round_trip(profiles, tmp_path):
    path = tmp_path / "models.toml"
    profiles["test"].scribes.append("x-ai/grok")
    save_model_profiles(profiles, path)

    loaded = load_model_profiles(path)
    assert loaded["test"].scribes[-1] == "x-ai/grok"
    assert loaded["quality"].chair == profiles["quality"].chair


def test_provider_of():
    assert provider_of("Anthropic/claude-haiku") == "anthropic"


def test_profiles_have_search_providers(profiles):
    for profile in profiles.values():
        assert profile.search == "openrouter_exa"  # works with the OpenRouter key alone
        assert profile.search_fallback == "duckduckgo"  # free, needs no key


def test_unknown_search_provider_is_rejected(profiles):
    p = copy.deepcopy(profiles["test"])
    p.search = "bing"
    assert any("Unknown web search provider 'bing'" in problem for problem in diversity_problems(p))


def test_search_round_trips_and_defaults_when_missing(profiles, tmp_path):
    path = tmp_path / "models.toml"
    profiles["test"].search = "tavily"
    save_model_profiles(profiles, path)
    assert load_model_profiles(path)["test"].search == "tavily"

    old_style = tmp_path / "old.toml"
    old_style.write_text(
        '[profiles.x]\ndefault = "a/1"\nscribes = ["a/1", "b/1"]\njurors = ["c/1"]\n'
        'chair = "d/1"\narchivist = "d/1"\nimage = "e/1"\nfallback = "f/1"\n', encoding="utf-8")
    assert load_model_profiles(old_style)["x"].search == "duckduckgo"
