"""The log panel: every LogEntry, colour-coded, with filters for agent, stage and level."""

from __future__ import annotations

from html import escape

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from bookguild.events import LogEntry
from bookguild.guild import all_agent_names
from bookguild.storage import STAGE_LABELS
from bookguild.ui.theme import LEVEL_COLORS

MAX_ENTRIES = 5000

LEVEL_FILTERS = {
    "All levels": None,
    "Warnings & errors": {"warning", "error"},
    "Errors only": {"error"},
}


class LogView(QWidget):
    def __init__(self):
        super().__init__()
        self.entries: list[LogEntry] = []

        self.agent_filter = QComboBox()
        self.agent_filter.addItem("All agents", None)
        for name in ["You", *all_agent_names()]:
            self.agent_filter.addItem(name, name)

        self.stage_filter = QComboBox()
        self.stage_filter.addItem("All stages", None)
        for stage, label in STAGE_LABELS.items():
            self.stage_filter.addItem(label, stage)

        self.level_filter = QComboBox()
        for label in LEVEL_FILTERS:
            self.level_filter.addItem(label)

        clear_button = QPushButton("Clear view")
        clear_button.setToolTip("Clears the panel only - the book's log file is kept.")
        clear_button.clicked.connect(self.clear)

        for combo in (self.agent_filter, self.stage_filter, self.level_filter):
            combo.currentIndexChanged.connect(self._redraw)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("<b>Log</b>"))
        filters.addStretch()
        filters.addWidget(self.agent_filter)
        filters.addWidget(self.stage_filter)
        filters.addWidget(self.level_filter)
        filters.addWidget(clear_button)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(MAX_ENTRIES)
        self.text.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(filters)
        layout.addWidget(self.text)

    def add_entry(self, entry: LogEntry) -> None:
        self.entries.append(entry)
        if len(self.entries) > MAX_ENTRIES:
            self.entries = self.entries[-MAX_ENTRIES:]
        if self.matches(entry):
            self.text.appendHtml(format_entry(entry))

    def set_entries(self, entries: list[LogEntry]) -> None:
        self.entries = list(entries[-MAX_ENTRIES:])
        self._redraw()

    def clear(self) -> None:
        self.entries = []
        self.text.clear()

    def visible_entries(self) -> list[LogEntry]:
        return [e for e in self.entries if self.matches(e)]

    def matches(self, entry: LogEntry) -> bool:
        agent = self.agent_filter.currentData()
        stage = self.stage_filter.currentData()
        levels = LEVEL_FILTERS[self.level_filter.currentText()]
        return (
            (agent is None or entry.agent == agent)
            and (stage is None or entry.stage == stage)
            and (levels is None or entry.level in levels)
        )

    def _redraw(self) -> None:
        self.text.clear()
        for entry in self.visible_entries():
            self.text.appendHtml(format_entry(entry))


def format_entry(entry: LogEntry) -> str:
    clock = entry.time[11:19] if len(entry.time) >= 19 else entry.time
    stage = f"[{STAGE_LABELS.get(entry.stage, entry.stage)}] " if entry.stage else ""
    agent = f"{entry.agent}: " if entry.agent else ""
    line = escape(f"{clock}  {stage}{agent}{entry.message}")
    if entry.level == "error":
        line = f"<b>{line}</b>"
    color = LEVEL_COLORS.get(entry.level)
    return f'<span style="color:{color}">{line}</span>' if color else line
