"""The Outline tab, in two columns:

    left:  the Council's verdict - one tab per Architect proposal (★ = the Council's choice),
           with the jurors' reasons, and the Chair's note underneath
    right: the working outline you edit and approve (title, subtitle, pitch, chapter table)
"""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from bookguild.events import Status
from bookguild.outline import ChapterPlan, Outline, Proposal
from bookguild.ui.theme import MUTED, STATUS_COLORS

LABELS = "ABCDEFGH"
CHAPTER_COLUMNS = ("Title", "Summary", "Key points (separate with |)", "Sources")
ROW_HEIGHT = 58  # about three lines of text

STATUS_TEXT = {
    Status.IDLE: ("Not started - run research first, then click 'Run Architects & Council'.", MUTED),
    Status.RUNNING: ("The Architects and the Council are working…", STATUS_COLORS[Status.RUNNING]),
    Status.WAITING: ("Waiting for you - compare the proposals, edit the outline, then Approve.",
                     STATUS_COLORS[Status.WAITING]),
    Status.DONE: ("Approved ✓  (editing will ask for approval again)", STATUS_COLORS[Status.DONE]),
    Status.FAILED: ("Failed - see the Failures tab, or run it again.", STATUS_COLORS[Status.FAILED]),
}


class ProposalCard(QFrame):
    def __init__(self, index: int, on_choose):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.header = QLabel()
        self.header.setWordWrap(True)
        self.body = QTextBrowser()
        self.choose_button = QPushButton(f"Use proposal {LABELS[index]}")
        self.choose_button.clicked.connect(lambda: on_choose(index))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.header)
        layout.addWidget(self.body, stretch=1)
        layout.addWidget(self.choose_button)


class OutlineView(QWidget):
    run_requested = Signal()
    apply_note_requested = Signal()
    choose_requested = Signal(int)
    save_requested = Signal(object)  # Outline
    approve_requested = Signal(object)  # Outline

    def __init__(self):
        super().__init__()
        self._loading = False
        self.has_outline = False

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.run_button = QPushButton("Run Architects && Council")  # "&&" shows a literal "&" in Qt
        self.run_button.clicked.connect(self.run_requested)
        self.note_button = QPushButton("Apply Chair's note")
        self.note_button.setToolTip("Ask the winning Architect to revise the outline using the Chair's note")
        self.note_button.clicked.connect(self.apply_note_requested)
        self.save_button = QPushButton("Save edits")
        self.save_button.clicked.connect(lambda: self.save_requested.emit(self.current_outline()))
        self.approve_button = QPushButton("Approve ✓")
        self.approve_button.clicked.connect(lambda: self.approve_requested.emit(self.current_outline()))
        top = QHBoxLayout()
        top.addWidget(self.status_label, stretch=1)
        for button in (self.run_button, self.note_button, self.save_button, self.approve_button):
            top.addWidget(button)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_verdict_panel())
        splitter.addWidget(self._build_editor())
        splitter.setSizes([520, 680])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addLayout(top)
        layout.addWidget(splitter, stretch=1)
        self.set_data(None, [], None, Status.IDLE)

    # ---------- building ----------

    def _build_verdict_panel(self) -> QWidget:
        panel = QWidget()
        self.verdict_label = QLabel()
        self.verdict_label.setWordWrap(True)
        self.proposal_tabs = QTabWidget()
        self.cards: list[ProposalCard] = []
        self.chair_note = QTextBrowser()
        notes_split = QSplitter(Qt.Orientation.Vertical)
        notes_split.addWidget(self.proposal_tabs)
        notes_split.addWidget(self.chair_note)
        notes_split.setSizes([400, 160])
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.verdict_label)
        layout.addWidget(notes_split, stretch=1)
        return panel

    def _build_editor(self) -> QWidget:
        editor = QWidget()
        self.title_edit, self.subtitle_edit, self.pitch_edit = QLineEdit(), QLineEdit(), QLineEdit()
        for edit in (self.title_edit, self.subtitle_edit, self.pitch_edit):
            edit.textChanged.connect(self._on_edit)
        self.pitch_edit.setPlaceholderText("1-2 sentences, like the back cover")
        form = QFormLayout()
        form.addRow("<b>Title</b>", self.title_edit)
        form.addRow("Subtitle", self.subtitle_edit)
        form.addRow("Pitch", self.pitch_edit)

        self.table = QTableWidget(0, len(CHAPTER_COLUMNS))
        self.table.setHorizontalHeaderLabels(CHAPTER_COLUMNS)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 220)
        self.table.itemChanged.connect(self._on_edit)

        buttons = QHBoxLayout()
        for text, slot in (("Add chapter", self._add_chapter), ("Remove", self._remove_chapter),
                           ("Move up", lambda: self._move(-1)), ("Move down", lambda: self._move(1))):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch()

        layout = QVBoxLayout(editor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("<b>Working outline</b> - starts as the Council's winner; edit freely"))
        layout.addLayout(form)
        layout.addWidget(self.table, stretch=1)
        layout.addLayout(buttons)
        self.editor = editor
        return editor

    # ---------- public ----------

    def set_data(self, outline: Outline | None, proposals: list[Proposal], verdict: dict | None,
                 status: str) -> None:
        self._show_verdict(proposals, verdict)
        self._loading = True
        self.has_outline = outline is not None
        outline = outline or Outline(title="")
        self.title_edit.setText(outline.title)
        self.subtitle_edit.setText(outline.subtitle)
        self.pitch_edit.setText(outline.pitch)
        self.table.setRowCount(0)
        for chapter in outline.chapters:
            self._append_row(chapter)
        self._loading = False
        self.editor.setEnabled(self.has_outline)
        self.save_button.setEnabled(False)
        self.note_button.setEnabled(bool(verdict and verdict.get("chair_note")) and self.has_outline)
        self.run_button.setText("Run Architects && Council again" if proposals else "Run Architects && Council")
        self.set_status(status)

    def set_status(self, status: str) -> None:
        text, color = STATUS_TEXT.get(status, STATUS_TEXT[Status.IDLE])
        self.status_label.setText(f"<b>Outline</b> - {text}")
        self.status_label.setStyleSheet(f"color: {color};")
        busy = status == Status.RUNNING
        self.run_button.setEnabled(not busy)
        self.approve_button.setEnabled(not busy and self.has_outline and status != Status.DONE)
        if busy:
            self.note_button.setEnabled(False)
            self.save_button.setEnabled(False)

    def current_outline(self) -> Outline:
        chapters = []
        for row in range(self.table.rowCount()):
            title = self._cell(row, 0)
            if not title:
                continue
            chapters.append(ChapterPlan(
                title=title, summary=self._cell(row, 1),
                key_points=[p.strip() for p in self._cell(row, 2).split("|") if p.strip()],
                sources=[s.strip().upper() for s in self._cell(row, 3).replace(",", " ").split() if s.strip()],
            ))
        return Outline(title=self.title_edit.text().strip() or "Untitled", subtitle=self.subtitle_edit.text().strip(),
                       pitch=self.pitch_edit.text().strip(), chapters=chapters)

    # ---------- verdict display ----------

    def _show_verdict(self, proposals: list[Proposal], verdict: dict | None) -> None:
        self.proposal_tabs.clear()
        while self.cards:
            self.cards.pop().deleteLater()
        if not proposals:
            self.verdict_label.setText(f"<span style='color:{MUTED}'>No proposals yet.</span>")
            self.chair_note.hide()
            return

        winner = verdict.get("winner") if verdict else None
        points = {int(k): v for k, v in (verdict or {}).get("points", {}).items()}
        weighted = {int(k): v for k, v in (verdict or {}).get("weighted", {}).items()}
        ballots = (verdict or {}).get("ballots", [])
        for index, proposal in enumerate(proposals):
            card = ProposalCard(index, self.choose_requested.emit)
            star = " ★ Council's choice" if index == winner else ""
            card.header.setText(
                f"<b>Proposal {LABELS[index]}{star}</b><br><span style='color:{MUTED}'>{proposal.architect} · "
                f"{escape(proposal.model)} · {points.get(index, 0)} points · score {weighted.get(index, 0)}/10</span>")
            if index == winner:
                card.setStyleSheet(f"ProposalCard {{ border: 2px solid {STATUS_COLORS[Status.DONE]}; "
                                   "border-radius: 6px; }")
            card.body.setHtml(proposal_html(proposal.outline, index, ballots))
            self.proposal_tabs.addTab(card, f"Proposal {LABELS[index]}{' ★' if index == winner else ''}")
            self.cards.append(card)
        if winner is not None and winner < len(self.cards):
            self.proposal_tabs.setCurrentIndex(winner)

        failed = (verdict or {}).get("failed_jurors") or []
        self.verdict_label.setText(
            f"<b>Council verdict</b> - {len(ballots)} juror(s) voted blind on shuffled proposals"
            + (f" · <span style='color:{STATUS_COLORS[Status.WAITING]}'>did not vote: {', '.join(failed)}</span>"
               if failed else ""))
        note = (verdict or {}).get("chair_note", "")
        self.chair_note.setVisible(bool(note))
        self.chair_note.setMarkdown(f"**Chair's note for improving the winner**\n\n{note}")

    # ---------- chapter table editing ----------

    def _append_row(self, chapter: ChapterPlan) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, value in enumerate((chapter.title, chapter.summary, " | ".join(chapter.key_points),
                                        " ".join(chapter.sources))):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            item.setToolTip(value)
            self.table.setItem(row, column, item)
        self.table.setRowHeight(row, ROW_HEIGHT)  # compact rows; click a cell to see and edit all of it

    def _add_chapter(self) -> None:
        self._append_row(ChapterPlan(title="New chapter"))
        self._on_edit()

    def _remove_chapter(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._on_edit()

    def _move(self, step: int) -> None:
        row = self.table.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.table.rowCount():
            return
        self._loading = True
        for column in range(self.table.columnCount()):
            a, b = self.table.takeItem(row, column), self.table.takeItem(target, column)
            self.table.setItem(row, column, b)
            self.table.setItem(target, column, a)
        self._loading = False
        self.table.setCurrentCell(target, self.table.currentColumn())
        self._on_edit()

    def _cell(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return item.text().strip() if item else ""

    def _on_edit(self, *_args) -> None:
        if self._loading:
            return
        self.save_button.setEnabled(True)
        self.approve_button.setEnabled(True)


def proposal_html(outline: Outline, index: int, ballots: list[dict]) -> str:
    parts = [f"<h3>{escape(outline.title)}</h3>"]
    if outline.subtitle:
        parts.append(f"<i>{escape(outline.subtitle)}</i>")
    if outline.pitch:
        parts.append(f"<p>{escape(outline.pitch)}</p>")
    parts.append("<ol>" + "".join(f"<li><b>{escape(c.title)}</b> - {escape(c.summary)}</li>"
                                  for c in outline.chapters) + "</ol>")
    reasons = [(b.get("juror", "?"), b.get("reasons", {}).get(str(index), "")) for b in ballots]
    if any(text for _, text in reasons):
        parts.append("<p><b>What the jurors said</b></p><ul>" +
                     "".join(f"<li>{escape(juror)}: {escape(text)}</li>" for juror, text in reasons if text) +
                     "</ul>")
    return "".join(parts)
