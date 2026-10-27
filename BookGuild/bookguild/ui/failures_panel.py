"""The Failures panel: every failed step, with Retry and Skip buttons.

A failure stays listed until you retry or skip it. Retrying runs the exact same call
again (through the gateway, so the usual retry limits still apply).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bookguild.reliability import Failure
from bookguild.storage import STAGE_LABELS
from bookguild.ui.theme import MUTED

COLUMNS = ("Time", "Stage", "Agent", "Model", "Error", "Attempts", "Type", "")


class FailuresPanel(QWidget):
    retry_requested = Signal(object)  # Failure
    count_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.failures: dict[int, Failure] = {}  # open failures by id

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        hint = QLabel("Retry runs the same step again · Skip hides it · Edit & retry arrives with the stage views")
        hint.setStyleSheet(f"color: {MUTED};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addWidget(hint)

    def add_failure(self, failure: Failure) -> None:
        self.failures[failure.id] = failure
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = (
            failure.time[11:19],
            STAGE_LABELS.get(failure.stage, failure.stage or "-"),
            failure.agent,
            failure.model,
            failure.error,
            str(failure.attempts),
            failure.kind,
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            self.table.setItem(row, column, item)
        self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, failure.id)
        self.table.setCellWidget(row, len(COLUMNS) - 1, self._action_buttons(failure))
        self.count_changed.emit(len(self.failures))

    def resolve(self, failure_id: int) -> None:
        if self.failures.pop(failure_id, None) is None:
            return
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == failure_id:
                self.table.removeRow(row)
                break
        self.count_changed.emit(len(self.failures))

    def _action_buttons(self, failure: Failure) -> QWidget:
        retry_button = QPushButton("Retry")
        retry_button.setEnabled(failure.retry is not None)
        retry_button.clicked.connect(lambda: self._retry(failure))
        skip_button = QPushButton("Skip")
        skip_button.clicked.connect(lambda: self.resolve(failure.id))

        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.addWidget(retry_button)
        layout.addWidget(skip_button)
        return box

    def _retry(self, failure: Failure) -> None:
        self.resolve(failure.id)  # if it fails again, a fresh failure row appears
        self.retry_requested.emit(failure)
