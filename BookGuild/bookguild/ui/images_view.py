"""The Images tab.

    left:  every image slot (chapter, what it should show, status)
    right: the selected slot - what it is for, buttons (find more / generate AI / upload my own /
           skip), and its candidates as cards: thumbnail, source, licence, author, print quality,
           and Approve / Reject. Only the approved image (or your upload) goes into the book.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bookguild.events import Status
from bookguild.images import APPROVED, REJECTED, SLOT_APPROVED, SLOT_SKIPPED, Candidate, ImageSlot, dpi_verdict, \
    print_dpi
from bookguild.profile import BookProfile
from bookguild.ui.theme import MUTED, STATUS_COLORS

COLUMNS = ("Slot", "Place", "What it shows", "Kind", "Status")
THUMB_WIDTH = 260
SLOT_COLORS = {SLOT_APPROVED: STATUS_COLORS[Status.DONE], SLOT_SKIPPED: MUTED}


class CandidateCard(QFrame):
    def __init__(self, view: "ImagesView", slot: ImageSlot, candidate: Candidate):
        super().__init__()
        self.setObjectName("CandidateCard")
        border = {APPROVED: STATUS_COLORS[Status.DONE], REJECTED: "rgba(128,128,128,0.25)"}.get(
            candidate.status, "rgba(128,128,128,0.45)")
        self.setStyleSheet(f"#CandidateCard {{ border: 2px solid {border}; border-radius: 6px; }}")

        picture = QLabel()
        pixmap = QPixmap(str(view.book_folder / candidate.preview))
        if not pixmap.isNull():
            thumb = pixmap.scaled(THUMB_WIDTH, THUMB_WIDTH, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
            picture.setPixmap(thumb)
            picture.setFixedSize(thumb.size())  # never squeezed under the text
        if candidate.status == REJECTED:
            picture.setEnabled(False)

        dpi = print_dpi(candidate, view.profile) if view.profile else 0
        verdict = dpi_verdict(dpi)
        dpi_color = STATUS_COLORS[Status.DONE] if dpi >= 300 else STATUS_COLORS[Status.WAITING] if dpi >= 200 \
            else STATUS_COLORS[Status.FAILED]
        link = f" · <a href='{escape(candidate.page_url)}'>source page</a>" if candidate.page_url else ""
        info = QLabel(
            f"<b>{escape(candidate.title[:70])}</b><br>"
            f"{escape(candidate.provider)} · {escape(candidate.license)}{link}<br>"
            + (f"<span style='color:{MUTED}'>found by: “{escape(candidate.found_by)}”</span><br>"
               if candidate.found_by else "") +
            f"<span style='color:{MUTED}'>by {escape(candidate.author[:60] or '-')}</span><br>"
            f"{candidate.width}×{candidate.height}px · <span style='color:{dpi_color}'>{dpi} dpi - {verdict}</span>"
            + (f"<br><b style='color:{STATUS_COLORS[Status.DONE]}'>✓ approved</b>" if candidate.status == APPROVED
               else "<br><span style='color:#8a8a8a'>rejected</span>" if candidate.status == REJECTED else ""))
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setOpenExternalLinks(True)
        info.setFixedWidth(THUMB_WIDTH)

        approve = QPushButton("Approve ✓")
        approve.setEnabled(candidate.status != APPROVED)
        approve.clicked.connect(lambda: view.approve_requested.emit(slot.id, candidate.id))
        reject = QPushButton("Reject")
        reject.setEnabled(candidate.status != REJECTED)
        reject.clicked.connect(lambda: view.reject_requested.emit(slot.id, candidate.id))
        buttons = QHBoxLayout()
        buttons.addWidget(approve)
        buttons.addWidget(reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(picture, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(info)
        layout.addLayout(buttons)
        self.setFixedSize(self.sizeHint())  # cards keep their size; the area scrolls instead of squeezing them


class ImagesView(QWidget):
    plan_requested = Signal()
    add_slot_requested = Signal(int, str, bool)  # chapter, purpose, real subject
    find_more_requested = Signal(str, str)  # slot id, your own search words ("" = the slot's phrases)
    generate_requested = Signal(str)
    upload_requested = Signal(str, Path)
    skip_requested = Signal(str)
    approve_requested = Signal(str, str)  # slot id, candidate id
    reject_requested = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.slots: list[ImageSlot] = []
        self.profile: BookProfile | None = None
        self.book_folder = Path(".")

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.plan_button = QPushButton("Find images for written chapters")
        self.plan_button.clicked.connect(self.plan_requested)
        add_button = QPushButton("Add image slot…")
        add_button.clicked.connect(self._ask_new_slot)
        credits_button = QPushButton("Credits")
        credits_button.setToolTip("Open images/credits.md - the licence credits for the book")
        credits_button.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.book_folder / "images" / "credits.md"))))
        top = QHBoxLayout()
        top.addWidget(self.status_label, stretch=1)
        for button in (self.plan_button, add_button, credits_button):
            top.addWidget(button)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.currentCellChanged.connect(lambda *_: self.show_slot())

        self.slot_header = QLabel()
        self.slot_header.setWordWrap(True)
        self.slot_buttons: dict[str, QPushButton] = {}
        slot_row = QHBoxLayout()
        for key, text, tip in (("find", "Find more licensed", "Search all of this slot's phrases again"),
                               ("own", "Search with my own words…", "Try a wider (or different) idea, e.g. "
                                                                    "'cosmic rays' or 'Bombay 1930s'"),
                               ("ai", "Generate AI image", "Paint an illustration (about $0.03); not for real people"),
                               ("upload", "Upload my own…", "Use your own image file; approved at once"),
                               ("skip", "Skip this slot", "Leave this place without an image")):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, k=key: self._slot_button(k))
            self.slot_buttons[key] = button
            slot_row.addWidget(button)
        slot_row.addStretch()

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        scroll = self.scroll
        self._new_cards_area()

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(self.slot_header)
        detail_layout.addLayout(slot_row)
        detail_layout.addWidget(scroll, stretch=1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(detail)
        splitter.setSizes([420, 820])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addLayout(top)
        layout.addWidget(splitter, stretch=1)
        self.set_slots([], None, Path("."), Status.IDLE)

    # ---------- public ----------

    def set_slots(self, slots: list[ImageSlot], profile: BookProfile | None, book_folder: Path, status: str) -> None:
        selected = self.selected_slot_id()
        self.slots, self.profile, self.book_folder = slots, profile, book_folder
        self.table.setRowCount(0)
        for slot in slots:
            row = self.table.rowCount()
            self.table.insertRow(row)
            kind = "real (licensed)" if slot.real_subject else slot.source
            place = "Chapter opener" if slot.role == "chapter" else "Section"
            for column, value in enumerate((slot.id, place, slot.purpose, kind, slot.status)):
                item = QTableWidgetItem(value)
                item.setToolTip(slot.caption or slot.purpose)
                if column == 1 and slot.role == "chapter":
                    item.setFont(_bold(item.font()))
                if column == 4:
                    item.setForeground(QColor(SLOT_COLORS.get(slot.status, STATUS_COLORS[Status.WAITING])))
                self.table.setItem(row, column, item)
        if slots:
            row = next((i for i, s in enumerate(slots) if s.id == selected), 0)
            self.table.selectRow(row)
        self.set_status(status)
        self.show_slot()

    def set_status(self, status: str) -> None:
        decided = sum(s.status in (SLOT_APPROVED, SLOT_SKIPPED) for s in self.slots)
        if status == Status.RUNNING:
            text, color = "The Curator is working… (watch the left panel and the log)", STATUS_COLORS[Status.RUNNING]
        elif not self.slots:
            text, color = "No images planned yet - write chapters, then click 'Find images'.", MUTED
        elif decided == len(self.slots):
            text, color = f"All {decided} image slots decided ✓", STATUS_COLORS[Status.DONE]
        else:
            text = f"{len(self.slots) - decided} of {len(self.slots)} slots need your choice - approve, upload or skip."
            color = STATUS_COLORS[Status.WAITING]
        self.status_label.setText(f"<b>Images</b> - {escape(text)}")
        self.status_label.setStyleSheet(f"color: {color};")
        busy = status == Status.RUNNING
        self.plan_button.setEnabled(not busy)
        for button in self.slot_buttons.values():
            button.setEnabled(not busy and self.selected_slot() is not None)

    def selected_slot_id(self) -> str | None:
        slot = self.selected_slot()
        return slot.id if slot else None

    def selected_slot(self) -> ImageSlot | None:
        row = self.table.currentRow()
        return self.slots[row] if 0 <= row < len(self.slots) else None

    def _new_cards_area(self) -> None:
        """A fresh card area; setWidget deletes the old one at once, so no stale cards stay painted."""
        self.cards_widget = QWidget()
        self.cards = QGridLayout(self.cards_widget)
        self.scroll.setWidget(self.cards_widget)

    def show_slot(self) -> None:
        self._new_cards_area()
        slot = self.selected_slot()
        if slot is None:
            self.slot_header.setText("")
            return
        real = " · <b>real subject: licensed images or your own only</b>" if slot.real_subject else ""
        place = "Chapter opener" if slot.role == "chapter" else "Section image"
        self.slot_header.setText(
            f"<b>{escape(slot.id)}</b> ({place}) - {escape(slot.purpose)}{real}<br>"
            f"<span style='color:{MUTED}'>Caption: {escape(slot.caption)}<br>"
            f"Goes next to: “{escape(slot.anchor)}”<br>"
            f"Searches (specific → wider): {escape(' · '.join(slot.queries()))}</span>")
        self.slot_buttons["ai"].setEnabled(not slot.real_subject and self.slot_buttons["find"].isEnabled())
        visible = sorted(slot.candidates, key=lambda c: (c.status == REJECTED, c.status != APPROVED))
        for i, candidate in enumerate(visible):
            self.cards.addWidget(CandidateCard(self, slot, candidate), i // 2, i % 2)
        if not slot.candidates:
            self.cards.addWidget(QLabel("No candidates - find more, generate one, or upload your own."), 0, 0)
        rows = (len(visible) + 1) // 2 or 1
        self.cards.setRowStretch(rows, 1)  # cards stay at the top-left; spare space goes below/right
        self.cards.setColumnStretch(2, 1)

    # ---------- actions ----------

    def _slot_button(self, key: str) -> None:
        slot = self.selected_slot()
        if slot is None:
            return
        if key == "find":
            self.find_more_requested.emit(slot.id, "")
        elif key == "own":
            query, ok = QInputDialog.getText(self, f"Search for {slot.id}",
                                             "Search Wikimedia Commons for (a person, place, object, idea or era):")
            if ok and query.strip():
                self.find_more_requested.emit(slot.id, query.strip())
        elif key == "ai":
            self.generate_requested.emit(slot.id)
        elif key == "skip":
            self.skip_requested.emit(slot.id)
        elif key == "upload":
            path, _ = QFileDialog.getOpenFileName(self, f"Your image for {slot.id}", "",
                                                  "Images (*.png *.jpg *.jpeg *.tif *.tiff *.webp)")
            if path:
                self.upload_requested.emit(slot.id, Path(path))

    def _ask_new_slot(self) -> None:
        chapter, ok = QInputDialog.getInt(self, "Add image slot", "Chapter number:", 1, 1, 60)
        if not ok:
            return
        purpose, ok = QInputDialog.getText(self, "Add image slot", "What should the image show?")
        if not ok or not purpose.strip():
            return
        real = QMessageBox.question(self, "Add image slot",
                                    "Does it show a real person, place or historical object?\n"
                                    "(Then only licensed images or your own upload are allowed.)") \
            == QMessageBox.StandardButton.Yes
        self.add_slot_requested.emit(chapter, purpose.strip(), real)


def _bold(font):
    font.setBold(True)
    return font
