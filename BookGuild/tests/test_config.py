from pathlib import Path

import pytest

from bookguild import config
from bookguild.config import load_settings

TEST_VAR = "BOOKGUILD_TEST_OPENROUTER_KEY"


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(
        f'[app]\nbooks_dir = "{tmp_path.as_posix()}/books"\n\n'
        f'[keys]\nopenrouter = "{TEST_VAR}"\ntavily = "BOOKGUILD_TEST_TAVILY_KEY"\n',
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def no_registry_lookup(monkeypatch):
    # Tests must only see what they put in os.environ, not the real Windows registry.
    monkeypatch.setattr(config, "_read_windows_registry_env", lambda env_var: None)


def test_default_settings_file_loads():
    settings = load_settings()
    assert settings.key_env_vars["openrouter"] == "OPENROUTER_API_KEY"
    assert settings.books_dir.name == "BookGuild"


def test_key_found_when_env_var_set(settings_file, monkeypatch):
    monkeypatch.setenv(TEST_VAR, "sk-or-secret-value")
    settings = load_settings(settings_file)

    assert settings.get_key("openrouter") == "sk-or-secret-value"
    assert settings.missing_required_keys() == []


def test_missing_and_blank_keys_are_reported(settings_file, monkeypatch):
    monkeypatch.setenv(TEST_VAR, "   ")
    settings = load_settings(settings_file)

    missing = settings.missing_required_keys()
    assert [s.env_var for s in missing] == [TEST_VAR]
    tavily = next(s for s in settings.key_statuses() if s.name == "tavily")
    assert not tavily.found and not tavily.required


def test_key_value_never_appears_in_statuses(settings_file, monkeypatch):
    monkeypatch.setenv(TEST_VAR, "sk-or-secret-value")
    settings = load_settings(settings_file)

    assert "sk-or-secret-value" not in repr(settings.key_statuses())
