"""The Guild roster: every named agent and the group it belongs to.

Phase 1 only uses this to draw the Guild Board. Later phases attach a model
and prompts to each member.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GuildGroup:
    name: str
    role: str
    members: tuple[str, ...]


GUILD: tuple[GuildGroup, ...] = (
    GuildGroup("Steward", "Chat & commands", ("Steward",)),
    GuildGroup("Cartographer", "Book profile", ("Cartographer",)),
    GuildGroup("Scouts", "Web research", ("Scout-1", "Scout-2", "Scout-3")),
    GuildGroup("Architects", "Title & outline", ("Architect-1", "Architect-2", "Architect-3")),
    GuildGroup("Scribes", "Chapter drafts", ("Scribe-1", "Scribe-2", "Scribe-3")),
    GuildGroup("Council", "Jury", ("Juror-1", "Juror-2", "Juror-3", "Chair")),
    GuildGroup("Archivist", "Fact-check", ("Archivist",)),
    GuildGroup("Curator", "Images", ("Curator",)),
    GuildGroup("Image Reviewer", "Visual review", ("Image Reviewer",)),
    GuildGroup("Illuminator", "Cover", ("Illuminator",)),
    GuildGroup("Binder", "Layout & export", ("Binder",)),
)


# Which agents work in which stage (drives the tree in the left panel).
STAGE_AGENTS: dict[str, tuple[str, ...]] = {
    "profile": ("Cartographer",),
    "research": ("Scout-1", "Scout-2", "Scout-3"),
    "outline": ("Architect-1", "Architect-2", "Architect-3", "Juror-1", "Juror-2", "Juror-3", "Chair"),
    "chapters": ("Scout-1", "Scout-2", "Scout-3", "Scribe-1", "Scribe-2", "Scribe-3",
                 "Juror-1", "Juror-2", "Juror-3", "Chair", "Archivist"),
    "images": ("Curator", "Image Reviewer"),
    "cover": ("Illuminator", "Image Reviewer"),
    "export": ("Binder",),
}


def all_agent_names() -> list[str]:
    return [member for group in GUILD for member in group.members]
