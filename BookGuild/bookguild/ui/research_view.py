"""The Research tab: every source the Scouts found (with quality scores) and the research brief.

Untick a source to exclude it: the brief is rebuilt without it, and later agents never see it.
Double-click a source to open it in your browser.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from bookguild.events import Status
from bookguild.research.sources import HIGH_QUALITY, Source
from bookguild.ui.theme import MUTED, STATUS_COLORS

COLUMNS = ("Use", "ID", "Quality", "Title", "Site", "Found by", "Text")

STATUS_TEXT = {
    Status.IDLE: ("Not started - approve the profile, then click 'Run research'.", MUTED),
    Status.RUNNING: ("The Scouts are researching… (watch the Guild Board and the log)", STATUS_COLORS[Status.RUNNING]),
    Status.DONE: ("Done - check the sources and untick any you don't trust.", STATUS_COLORS[Status.DONE]),
    Status.FAILED: ("Research failed - see the Failures tab, or run it again.", STATUS_COLORS[Status.FAILED]),
}


class ResearchView(QWidget):
    run_requested = Signal()
    exclusion_changed = Signal(str, bool)  # source id, excluded

    def __init__(self):
        super().__init__()
        self._loading = False

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.run_button = QPushButton("Run research")
        self.run_button.setToolTip("Send the three Scouts out. Running again replaces the current sources.")
        self.run_button.clicked.connect(self.run_requested)
        top = QHBoxLayout()
        top.addWidget(self.status_label, stretch=1)
        top.addWidget(self.run_button)

        self.summary_label = QLabel()
        self.summary_label.setStyleSheet(f"color: {MUTED};")

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(self._open_source)

        self.brief = QTextBrowser()
        self.brief.setOpenExternalLinks(True)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.brief)
        splitter.setSizes([600, 500])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.summary_label)
        layout.addWidget(splitter, stretch=1)
        self.sources: list[Source] = []
        self.set_status(Status.IDLE)

    def set_status(self, status: str) -> None:
        text, color = STATUS_TEXT.get(status, STATUS_TEXT[Status.IDLE])
        self.status_label.setText(f"<b>Research</b> - {text}")
        self.status_label.setStyleSheet(f"color: {color};")
        self.run_button.setEnabled(status != Status.RUNNING)
        self.run_button.setText("Run research again" if self.sources else "Run research")

    def set_research(self, sources: list[Source], brief_markdown: str) -> None:
        self._loading = True
        self.sources = sources
        self.table.setRowCount(0)
        for source in sources:
            self._add_row(source)
        self._loading = False
        self.brief.setMarkdown(brief_markdown or "_No research brief yet._")
        self._update_summary()
        self.run_button.setText("Run research again" if sources else "Run research")

    def _add_row(self, source: Source) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        use = QTableWidgetItem()
        use.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        use.setCheckState(Qt.CheckState.Unchecked if source.excluded else Qt.CheckState.Checked)
        use.setData(Qt.ItemDataRole.UserRole, source.id)
        quality = QTableWidgetItem(str(source.quality))
        quality.setToolTip(source.quality_note)
        quality.setForeground(QColor(STATUS_COLORS[Status.DONE] if source.quality >= HIGH_QUALITY
                                     else STATUS_COLORS[Status.WAITING] if source.quality < 50 else MUTED))
        values = [use, QTableWidgetItem(source.id), quality, QTableWidgetItem(source.title),
                  QTableWidgetItem(source.domain), QTableWidgetItem(", ".join(source.found_by)),
                  QTableWidgetItem("full page" if source.full_text else "excerpt")]
        for column, item in enumerate(values):
            item.setToolTip(item.toolTip() or f"{source.url}\n\n{source.text[:600]}")
            self.table.setItem(row, column, item)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 0:
            return
        source_id = item.data(Qt.ItemDataRole.UserRole)
        self.exclusion_changed.emit(source_id, item.checkState() == Qt.CheckState.Unchecked)

    def _open_source(self, row: int, _column: int) -> None:
        if 0 <= row < len(self.sources):
            QDesktopServices.openUrl(QUrl(self.sources[row].url))

    def _update_summary(self) -> None:
        used = [s for s in self.sources if not s.excluded]
        if not self.sources:
            self.summary_label.setText("")
            return
        high = sum(1 for s in used if s.quality >= HIGH_QUALITY)
        full = sum(1 for s in used if s.full_text)
        excluded = len(self.sources) - len(used)
        self.summary_label.setText(
            f"{len(used)} sources in use · {high} high quality (score ≥ {HIGH_QUALITY}) · {full} full pages read"
            + (f" · {excluded} excluded by you" if excluded else "")
            + " · untick to exclude, double-click to open")
