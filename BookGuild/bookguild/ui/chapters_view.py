"""The Chapters tab.

    left:  every chapter with its status / current step, words, fact-check flags, cost and winning Scribe
    right: the selected chapter - the text, the drafts and the Council's votes, the Archivist's
           fact-check, and the chapter's research notes
"""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from bookguild.budget import format_usd
from bookguild.chapters import ChapterRecord, strip_markers
from bookguild.events import Status
from bookguild.ui.theme import MUTED, STATUS_COLORS, STATUS_LABELS

COLUMNS = ("#", "Chapter", "Status", "Words", "Flags", "Cost", "Winner")
LABELS = "ABCDEFGH"


class ChaptersView(QWidget):
    write_requested = Signal()  # write every chapter not done yet
    rewrite_requested = Signal(int)  # chapter number, from scratch
    revise_requested = Signal(int, str)  # chapter number, your instruction

    def __init__(self):
        super().__init__()
        self.records: list[ChapterRecord] = []
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.write_button = QPushButton("Write remaining chapters")
        self.write_button.clicked.connect(self.write_requested)
        self.rewrite_button = QPushButton("Write / rewrite selected")
        self.rewrite_button.setToolTip("Write just the selected chapter (from scratch if it was written before). "
                                       "To try other models, switch AI > Model profile: each profile has its own "
                                       "workspace.")
        self.rewrite_button.clicked.connect(lambda: self._with_selected(self.rewrite_requested.emit))
        self.revise_button = QPushButton("Revise selected…")
        self.revise_button.setToolTip("Tell a Scribe what to change; the Archivist checks the result")
        self.revise_button.clicked.connect(self._ask_revision)
        top = QHBoxLayout()
        top.addWidget(self.status_label, stretch=1)
        for button in (self.write_button, self.rewrite_button, self.revise_button):
            top.addWidget(button)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.currentCellChanged.connect(lambda *_: self.chapter_selected())

        self.text_view = QTextBrowser()
        self.markers_box = QCheckBox("Show source markers [S#]")
        self.markers_box.toggled.connect(lambda _: self.chapter_selected())
        text_tab = QWidget()
        text_layout = QVBoxLayout(text_tab)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.addWidget(self.markers_box)
        text_layout.addWidget(self.text_view)
        self.votes_view, self.check_view, self.research_view = QTextBrowser(), QTextBrowser(), QTextBrowser()
        self.research_view.setOpenExternalLinks(True)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.addTab(text_tab, "Chapter")
        self.detail_tabs.addTab(self.votes_view, "Drafts && votes")
        self.detail_tabs.addTab(self.check_view, "Fact-check")
        self.detail_tabs.addTab(self.research_view, "Research")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail_tabs)
        splitter.setSizes([520, 700])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addLayout(top)
        layout.addWidget(splitter, stretch=1)
        self.loader = None  # set by the window: loader(number) -> dict of the chapter's files
        self.set_records([], Status.IDLE, {})

    # ---------- public ----------

    def set_records(self, records: list[ChapterRecord], stage_status: str, costs: dict[int, float]) -> None:
        selected = self.selected_number()
        self.records = records
        self.table.setRowCount(0)
        for record in records:
            self._add_row(record, costs.get(record.number, 0.0))
        if records:
            row = next((i for i, r in enumerate(records) if r.number == selected), 0)
            self.table.selectRow(row)
        self.set_status(stage_status)
        self.chapter_selected()

    def set_status(self, status: str) -> None:
        done = sum(r.status == Status.DONE for r in self.records)
        running = [r for r in self.records if r.status == Status.RUNNING]
        if not self.records:
            text, color = "Approve the outline first - then the Scribes can write.", MUTED
        elif status == Status.RUNNING or running:
            text, color = (f"Writing… {done} of {len(self.records)} done "
                           f"({', '.join(f'ch {r.number}: {r.step}' for r in running)})"), STATUS_COLORS[Status.RUNNING]
        elif done == len(self.records):
            flags = sum(r.flags for r in self.records)
            text = f"All {done} chapters written" + (f" - {flags} fact-check flag(s) to review" if flags else " ✓")
            color = STATUS_COLORS[Status.WAITING] if flags else STATUS_COLORS[Status.DONE]
        else:
            text, color = f"{done} of {len(self.records)} chapters written.", MUTED
        self.status_label.setText(f"<b>Chapters</b> - {escape(text)}")
        self.status_label.setStyleSheet(f"color: {color};")
        busy = status == Status.RUNNING or bool(running)
        has_records = bool(self.records)
        self.write_button.setEnabled(has_records and not busy and done < len(self.records))
        self.rewrite_button.setEnabled(has_records and not busy)
        self.revise_button.setEnabled(has_records and not busy)

    def selected_number(self) -> int | None:
        row = self.table.currentRow()
        return self.records[row].number if 0 <= row < len(self.records) else None

    def chapter_selected(self) -> None:
        number = self.selected_number()
        files = self.loader(number) if (self.loader and number) else {}
        text = files.get("final") or files.get("revised") or ""
        if text:
            self.text_view.setMarkdown(text if self.markers_box.isChecked() else strip_markers(text))
        else:
            self.text_view.setMarkdown("_Not written yet._")
        self.votes_view.setHtml(votes_html(files.get("drafts"), files.get("jury")))
        self.check_view.setHtml(factcheck_html(files.get("factcheck")))
        self.research_view.setMarkdown(files.get("research") or "_No chapter research yet._")

    # ---------- internals ----------

    def _add_row(self, record: ChapterRecord, cost: float) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        status = record.step if record.status == Status.RUNNING and record.step else \
            STATUS_LABELS.get(record.status, record.status)
        if record.status == Status.FAILED and record.step:
            status = record.step
        values = (str(record.number), record.title, status, str(record.words or ""),
                  str(record.flags) if record.status == Status.DONE else "", format_usd(cost) if cost else "",
                  record.winner)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 2:
                item.setForeground(QColor(STATUS_COLORS.get(record.status, MUTED)))
                item.setToolTip(record.error or value)
            if column == 4 and record.flags:
                item.setForeground(QColor(STATUS_COLORS[Status.WAITING]))
            self.table.setItem(row, column, item)

    def _with_selected(self, action) -> None:
        number = self.selected_number()
        if number:
            action(number)

    def _ask_revision(self) -> None:
        number = self.selected_number()
        if not number:
            return
        text, ok = QInputDialog.getMultiLineText(self, f"Revise chapter {number}",
                                                 "What should change? (e.g. 'simpler words', "
                                                 "'more about his school years', 'shorter ending')")
        if ok and text.strip():
            self.revise_requested.emit(number, text.strip())


def votes_html(drafts: list | None, jury: dict | None) -> str:
    if not drafts or not jury:
        return f"<p style='color:{MUTED}'>No drafts yet.</p>"
    points = {int(k): v for k, v in jury.get("points", {}).items()}
    weighted = {int(k): v for k, v in jury.get("weighted", {}).items()}
    winner = jury.get("winner")
    parts = [f"<p><b>{len(jury.get('ballots', []))} juror(s) voted blind.</b>"
             + (f" Did not vote: {', '.join(jury['failed_jurors'])}." if jury.get("failed_jurors") else "") + "</p>"]
    if jury.get("chair_note"):
        parts.append(f"<p><b>Chair's note (applied once to the winner):</b><br>"
                     f"{escape(jury['chair_note']).replace(chr(10), '<br>')}</p>")
    for i, draft in enumerate(drafts):
        star = " ★ winner" if i == winner else ""
        reasons = "".join(f"<li>{escape(b.get('juror', '?'))}: {escape(b.get('reasons', {}).get(str(i), ''))}</li>"
                          for b in jury.get("ballots", []))
        parts.append(f"<hr><h3>Draft {LABELS[i]}{star} - {escape(draft['scribe'])} ({escape(draft['model'])})</h3>"
                     f"<p style='color:{MUTED}'>{points.get(i, 0)} points · score {weighted.get(i, 0)}/10</p>"
                     f"<ul>{reasons}</ul>"
                     f"<details><pre style='white-space: pre-wrap'>{escape(strip_markers(draft['text']))}</pre>"
                     f"</details>")
    return "".join(parts)


def factcheck_html(report: dict | None) -> str:
    if not report:
        return f"<p style='color:{MUTED}'>Not fact-checked yet.</p>"

    def block(title: str, check: dict) -> str:
        rows = "".join(
            f"<li><b style='color:{STATUS_COLORS[Status.FAILED] if f['severity'] in ('critical', 'major') else MUTED}'>"
            f"{escape(f['severity'])}</b> \"{escape(f['quote'])}\" - {escape(f['problem'])}"
            f"<br><i>fix: {escape(f['fix'])}</i></li>" for f in check.get("findings", []))
        verdict = "✓ approved" if check.get("approved") else "✗ problems found"
        return f"<h3>{title}: {verdict}</h3><p>{escape(check.get('summary', ''))}</p><ul>{rows or '<li>none</li>'}</ul>"

    html = block("Archivist's check", report["first"])
    if report.get("after_fix"):
        html += "<hr>" + block("Re-check after one fix pass", report["after_fix"])
    return html
