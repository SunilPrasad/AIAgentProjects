"""The stage timeline across the top: Profile ▸ Research ▸ ... ▸ Export, coloured by status."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from bookguild.events import Status
from bookguild.storage import STAGE_LABELS, STAGES
from bookguild.ui.theme import MUTED, STATUS_COLORS, STATUS_LABELS


class StageTimeline(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.chips: dict[str, QLabel] = {}
        for i, stage in enumerate(STAGES):
            if i > 0:
                arrow = QLabel("▸")
                arrow.setStyleSheet(f"color: {MUTED};")
                layout.addWidget(arrow)
            chip = QLabel(STAGE_LABELS[stage])
            self.chips[stage] = chip
            layout.addWidget(chip)
            self.set_stage_status(stage, Status.IDLE)
        layout.addStretch()

    def set_stage_status(self, stage: str, status: str) -> None:
        chip = self.chips.get(stage)
        if chip is None:
            return
        color = STATUS_COLORS.get(status, STATUS_COLORS[Status.IDLE])
        chip.setStyleSheet(
            f"background: {color}; color: white; border-radius: 10px; padding: 3px 12px; font-weight: bold;"
        )
        chip.setToolTip(f"{STAGE_LABELS[stage]}: {STATUS_LABELS.get(status, status)}")
        chip.setProperty("status", status)

    def set_all(self, stages: dict[str, str]) -> None:
        for stage, status in stages.items():
            self.set_stage_status(stage, status)
