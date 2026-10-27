"""Developer tools for checking the UI without spending any money.

- DemoRun: a scripted fake pipeline run (Developer > Run demo events). It only emits
  events on the EventBus; it never calls an AI model or changes saved stage progress.
- AlwaysTimeoutClient: a fake AI client used to watch the retry logic work.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer

from bookguild.events import EventBus, Status
from bookguild.llm import LLMResult
from bookguild.reliability import TransientError

# Each step is (kind, *args):
#   ("stage", stage, status)
#   ("agent", agent, status, detail)
#   ("log", stage, agent, level, message)
#   ("cost", spent_usd)
DEMO_STEPS = [
    ("log", "", "Steward", "info", "(demo) Starting a simulated run - no AI calls, $0."),
    ("stage", "profile", Status.RUNNING),
    ("agent", "Cartographer", Status.RUNNING, "drafting profile"),
    ("log", "profile", "Cartographer", "info", "(demo) Drafting book profile: evidence mode, adult readers"),
    ("agent", "Cartographer", Status.DONE, "profile ready"),
    ("cost", 0.01),
    ("stage", "profile", Status.DONE),
    ("stage", "research", Status.RUNNING),
    ("agent", "Scout-1", Status.RUNNING, "history angle"),
    ("agent", "Scout-2", Status.RUNNING, "science angle"),
    ("agent", "Scout-3", Status.RUNNING, "culture angle"),
    ("log", "research", "Scout-1", "info", "(demo) Searching: 'origins of tea cultivation China'"),
    ("log", "research", "Scout-3", "info", "(demo) Searching: 'tea ceremony traditions Japan'"),
    ("log", "research", "Scout-2", "warning", "(demo) Timeout from search provider - retry 1 of 3"),
    ("log", "research", "Scout-1", "success", "(demo) Found 12 sources (8 high quality)"),
    ("agent", "Scout-1", Status.DONE, "12 sources"),
    ("log", "research", "Scout-2", "error", "(demo) Failed after 3 attempts: search provider timeout"),
    ("agent", "Scout-2", Status.FAILED, "timeout x3"),
    ("agent", "Scout-3", Status.DONE, "9 sources"),
    ("cost", 0.06),
    ("log", "research", "Steward", "info", "(demo) 2 of 3 Scouts succeeded - merging their briefs"),
    ("stage", "research", Status.DONE),
    ("stage", "outline", Status.RUNNING),
    ("agent", "Architect-1", Status.RUNNING, "proposing outline"),
    ("agent", "Architect-2", Status.RUNNING, "proposing outline"),
    ("agent", "Architect-3", Status.RUNNING, "proposing outline"),
    ("agent", "Architect-1", Status.DONE, "10 chapters"),
    ("agent", "Architect-2", Status.DONE, "12 chapters"),
    ("agent", "Architect-3", Status.DONE, "9 chapters"),
    ("cost", 0.09),
    ("agent", "Juror-1", Status.RUNNING, "scoring A/B/C"),
    ("agent", "Juror-2", Status.RUNNING, "scoring A/B/C"),
    ("agent", "Juror-3", Status.RUNNING, "scoring A/B/C"),
    ("agent", "Juror-1", Status.DONE, "ranked B > A > C"),
    ("agent", "Juror-2", Status.DONE, "ranked B > C > A"),
    ("agent", "Juror-3", Status.DONE, "ranked A > B > C"),
    ("agent", "Chair", Status.DONE, "winner: B"),
    ("log", "outline", "Chair", "success", "(demo) Council chose outline B (Borda score 8)"),
    ("cost", 0.12),
    ("stage", "outline", Status.WAITING),
    ("log", "outline", "Steward", "info", "(demo) Outline is waiting for your approval. Demo finished."),
]


class AlwaysTimeoutClient:
    """Stands in for OpenRouterClient and times out on every call (Developer > Simulate timeout)."""

    async def chat(self, model: str, messages: list[dict], **kwargs) -> LLMResult:
        raise TransientError("Request to OpenRouter timed out (simulated)")


class DemoRun(QObject):
    def __init__(self, bus: EventBus, budget_usd: float, step_ms: int = 350):
        super().__init__()
        self.bus = bus
        self.budget_usd = budget_usd
        self.index = 0
        self.stage = ""  # the stage the demo is currently in, so agent updates land under it
        self.timer = QTimer(self)
        self.timer.setInterval(step_ms)
        self.timer.timeout.connect(self._next_step)

    def start(self) -> None:
        self.index = 0
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()

    def is_running(self) -> bool:
        return self.timer.isActive()

    def _next_step(self) -> None:
        if self.index >= len(DEMO_STEPS):
            self.timer.stop()
            return

        kind, *args = DEMO_STEPS[self.index]
        self.index += 1

        if kind == "stage":
            self.bus.set_stage_status(*args)
            if args[1] == Status.RUNNING:
                self.stage = args[0]
        elif kind == "agent":
            agent, status, detail = args
            self.bus.set_agent_status(agent, status, detail, self.stage)
        elif kind == "log":
            stage, agent, level, message = args
            self.bus.log(message, level=level, stage=stage, agent=agent)
        elif kind == "cost":
            self.bus.set_cost(args[0], self.budget_usd)
