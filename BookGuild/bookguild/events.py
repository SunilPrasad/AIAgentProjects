"""The EventBus: how stages and agents tell the UI what is happening.

Stages and agents call methods like `bus.log(...)` or `bus.set_agent_status(...)`.
The UI connects to the signals and redraws. Nothing in this module knows about widgets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QObject, Signal


class Status:
    """Status values shared by stages and agents."""

    IDLE = "idle"  # not started yet
    RUNNING = "running"
    WAITING = "waiting"  # waiting for your approval
    DONE = "done"
    FAILED = "failed"

    ALL = (IDLE, RUNNING, WAITING, DONE, FAILED)


LOG_LEVELS = ("debug", "info", "success", "warning", "error")


@dataclass
class LogEntry:
    message: str
    level: str = "info"
    stage: str = ""  # e.g. "research"; empty means general
    agent: str = ""  # e.g. "Scout-1", "You", "Steward"
    time: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class EventBus(QObject):
    log_added = Signal(object)  # LogEntry
    agent_status_changed = Signal(str, str, str, str)  # agent, status, detail, stage ("" = general)
    stage_status_changed = Signal(str, str)  # stage, status
    cost_changed = Signal(float, float)  # spent_usd, budget_usd
    failure_added = Signal(object)  # reliability.Failure
    pipeline_paused = Signal(str)  # reason
    pipeline_resumed = Signal()
    profile_changed = Signal(object)  # profile.BookProfile (or None)
    steward_replied = Signal(str)  # the Steward's latest chat answer
    research_changed = Signal()  # sources or the research brief changed
    outline_changed = Signal()  # proposals, verdict or the working outline changed
    chapters_changed = Signal(int)  # a chapter's record or files changed (its number)
    images_changed = Signal()  # image slots, candidates or decisions changed
    style_samples_changed = Signal()  # book-wide reference images changed
    cover_changed = Signal()  # cover settings, concepts or approval changed

    def log(self, message: str, level: str = "info", stage: str = "", agent: str = "") -> None:
        self.log_added.emit(LogEntry(message=message, level=level, stage=stage, agent=agent))

    def set_agent_status(self, agent: str, status: str, detail: str = "", stage: str = "") -> None:
        self.agent_status_changed.emit(agent, status, detail, stage)

    def set_stage_status(self, stage: str, status: str) -> None:
        self.stage_status_changed.emit(stage, status)

    def set_cost(self, spent_usd: float, budget_usd: float) -> None:
        self.cost_changed.emit(spent_usd, budget_usd)
