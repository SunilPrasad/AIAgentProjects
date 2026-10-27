"""Loads agent prompts from bookguild/prompts/*.md and fills in {{placeholders}}.

Prompts live in Markdown files, not in code, so they are easy to read and tune.
"""

from __future__ import annotations

import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


def render(name: str, **values: str) -> str:
    """render("cartographer", brief="...") -> the text of prompts/cartographer.md with {{brief}} filled in."""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    leftover = re.findall(r"\{\{(\w+)\}\}", text)
    if leftover:
        raise KeyError(f"Prompt '{name}' needs values for: {', '.join(sorted(set(leftover)))}")
    return text
