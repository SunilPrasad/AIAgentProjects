"""Stage 1 - Book Profile.

The Cartographer reads brief.md and drafts the Book Profile (or revises it on request).
These functions only do the AI work and return a validated profile; saving it and
updating the stage status is done by BookSession.
"""

from __future__ import annotations

from bookguild import prompts, storage
from bookguild.gateway import AIGateway
from bookguild.models import ModelProfile
from bookguild.profile import BookProfile
from bookguild.storage import Book

# Planning is a structured JSON job: hidden "thinking" made cheap models run out of tokens
# (3 of 4 replies cut off in testing), so it is switched off. With it off, replies are ~600 tokens.
MAX_TOKENS = 4000
REQUIRED_KEYS = ("working_title", "mode", "audience_age", "target_pages", "chapter_count")


async def draft_profile(book: Book, gateway: AIGateway, models: ModelProfile) -> tuple[BookProfile, list[str]]:
    """Brief -> new profile. Returns (profile, warnings about values that had to be fixed)."""
    prompt = prompts.render("cartographer", brief=storage.read_brief(book))
    result = await gateway.chat_json(
        agent="Cartographer", stage="profile", model=models.default, fallback_model=models.fallback,
        messages=[{"role": "user", "content": prompt}], max_tokens=MAX_TOKENS,
        thinking="off", required_keys=REQUIRED_KEYS,
    )
    return BookProfile.from_dict(result.data)


async def revise_profile(book: Book, gateway: AIGateway, models: ModelProfile, current: BookProfile,
                         instruction: str) -> tuple[BookProfile, list[str]]:
    """Current profile + your change request -> updated profile."""
    prompt = prompts.render("cartographer_revise", brief=storage.read_brief(book),
                            profile=current.for_prompt(), instruction=instruction)
    result = await gateway.chat_json(
        agent="Cartographer", stage="profile", model=models.default, fallback_model=models.fallback,
        messages=[{"role": "user", "content": prompt}], max_tokens=MAX_TOKENS,
        thinking="off", required_keys=REQUIRED_KEYS,
    )
    return BookProfile.from_dict(result.data)
