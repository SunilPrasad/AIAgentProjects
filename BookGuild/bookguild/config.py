"""Loads config/settings.toml and checks which API keys are available.

API keys are only ever read from environment variables. This module never
stores, prints or logs a key's value - only whether it was found.
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.toml"

# Keys the app cannot work without. Everything else is optional.
REQUIRED_KEYS = ("openrouter",)


@dataclass
class KeyStatus:
    name: str  # logical name, e.g. "openrouter"
    env_var: str  # environment variable name, e.g. "OPENROUTER_API_KEY"
    found: bool
    required: bool


@dataclass
class Settings:
    books_dir: Path
    key_env_vars: dict[str, str]  # logical name -> environment variable name
    model_profile: str = "test"  # which profile in config/models.toml is active
    contact: str = ""  # optional email/website sent to Wikimedia, whose robot policy asks tools for contact details

    def user_agent(self) -> str:
        """How web requests identify the app. Wikimedia refuses anonymous-looking tools."""
        return f"BookGuild/0.1 ({self.contact or 'https://github.com/bookguild/book-guild'}) httpx"

    def get_key(self, name: str) -> str | None:
        """Return the API key value for `name`, or None if it is not set."""
        env_var = self.key_env_vars.get(name)
        if not env_var:
            return None
        return read_env_var(env_var)

    def key_statuses(self) -> list[KeyStatus]:
        return [
            KeyStatus(
                name=name,
                env_var=env_var,
                found=self.get_key(name) is not None,
                required=name in REQUIRED_KEYS,
            )
            for name, env_var in self.key_env_vars.items()
        ]

    def missing_required_keys(self) -> list[KeyStatus]:
        return [s for s in self.key_statuses() if s.required and not s.found]


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> Settings:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    app = data.get("app", {})
    books_dir = Path(app.get("books_dir", "~/Documents/BookGuild")).expanduser()
    return Settings(
        books_dir=books_dir,
        key_env_vars=dict(data.get("keys", {})),
        model_profile=app.get("model_profile", "test"),
        contact=app.get("contact", ""),
    )


KEY_COMMENTS = {
    "openrouter": "required",
    "tavily": "optional - research (Phase 4)",
    "exa": "optional - research (Phase 4)",
    "pexels": "optional - images (Phase 7)",
    "pixabay": "optional - images (Phase 7)",
    "unsplash": "optional - images (Phase 7)",
}


def save_settings(settings: Settings, path: Path = DEFAULT_SETTINGS_PATH) -> None:
    """Write settings back to settings.toml, keeping the explanatory comments."""
    lines = [
        "# Book Guild settings.",
        "# This file is safe to commit: it never contains secrets.",
        "",
        "[app]",
        "# Where each book gets its own folder.",
        f"books_dir = {_toml_string(settings.books_dir.as_posix())}",
        "# Active model profile from config/models.toml: test | balanced | quality",
        f"model_profile = {_toml_string(settings.model_profile)}",
        "# Optional: your email or website, sent to Wikimedia (its robot policy asks tools for contact details).",
        f"contact = {_toml_string(settings.contact)}",
        "",
        "# The NAMES of the environment variables that hold your API keys.",
        "# The keys themselves stay in your Windows environment and are never written to disk or logs.",
        "# Change a name here if your variable is called something else.",
        "[keys]",
    ]
    for name, env_var in settings.key_env_vars.items():
        comment = KEY_COMMENTS.get(name, "optional")
        lines.append(f"{name:<10} = {_toml_string(env_var):<22}  # {comment}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _toml_string(value: str) -> str:
    # A JSON string is also a valid TOML basic string.
    return json.dumps(value)


def read_env_var(env_var: str) -> str | None:
    """Read an environment variable, treating blank values as missing.

    On Windows, a variable added after this program (or its terminal/IDE) was
    started is not in os.environ yet, so we also look it up in the registry.
    """
    value = os.environ.get(env_var) or _read_windows_registry_env(env_var)
    if value is None or not value.strip():
        return None
    return value.strip()


def _read_windows_registry_env(env_var: str) -> str | None:
    if sys.platform != "win32":
        return None

    import winreg

    locations = [
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ]
    for hive, subkey in locations:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, env_var)
                return str(value)
        except OSError:
            continue
    return None
