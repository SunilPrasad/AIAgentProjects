"""The Cover tab.

    left:   the Illuminator's concepts (art + name) - click "Use" to apply one
    middle: what the cover says and how it looks: title, subtitle, author, blurb, colours,
            title position, "my art already has the title", page count (sets the spine width)
    right:  a live preview of the whole KDP wrap cover, with optional guides
            (red dashed = trim and spine lines, blue dotted = KDP barcode area)
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from bookguild.cover import CoverSpec, render_wrap, spine_width_in, SPINE_TEXT_MIN_PAGES, wrap_size_in
from bookguild.events import Status
from bookguild.profile import BookProfile
from bookguild.ui.theme import MUTED, STATUS_COLORS

PREVIEW_SCALE = 0.35  # the on-screen preview is drawn at ~100 dpi: same design, much faster

STATUS_TEXT = {
    Status.IDLE: ("No cover yet - click 'Make cover concepts', or upload your own front art.", MUTED),
    Status.RUNNING: ("The Illuminator is designing… (about a minute)", STATUS_COLORS[Status.RUNNING]),
    Status.WAITING: ("Pick a concept, check the text and the preview, then Approve.", STATUS_COLORS[Status.WAITING]),
    Status.DONE: ("Approved ✓ - cover/wrap.pdf and ebook.jpg are ready. Editing asks for approval again.",
                  STATUS_COLORS[Status.DONE]),
    Status.FAILED: ("Failed - see the Failures tab, or try again.", STATUS_COLORS[Status.FAILED]),
}


class CoverView(QWidget):
    make_requested = Signal()
    upload_requested = Signal(str, Path)  # "front"/"back", file
    concept_chosen = Signal(str)
    save_requested = Signal(object)  # CoverSpec
    approve_requested = Signal(object)  # CoverSpec

    def __init__(self):
        super().__init__()
        self.spec = CoverSpec()
        self.profile = BookProfile()
        self.book = None
        self.estimated_pages = 0
        self._loading = False

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.make_button = QPushButton("Make cover concepts (≈ $0.30)")
        self.make_button.clicked.connect(self.make_requested)
        front_button = QPushButton("Upload front art…")
        front_button.clicked.connect(lambda: self._upload("front"))
        back_button = QPushButton("Upload back art…")
        back_button.clicked.connect(lambda: self._upload("back"))
        self.approve_button = QPushButton("Approve cover ✓")
        self.approve_button.setToolTip("Writes cover/wrap.pdf (KDP paperback) and cover/ebook.jpg (Kindle)")
        self.approve_button.clicked.connect(lambda: self.approve_requested.emit(self.current_spec()))
        top = QHBoxLayout()
        top.addWidget(self.status_label, stretch=1)
        for button in (self.make_button, front_button, back_button, self.approve_button):
            top.addWidget(button)

        self.concepts_scroll = QScrollArea()
        self.concepts_scroll.setWidgetResizable(True)
        self.concepts_scroll.setMinimumWidth(230)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(300, 200)
        self.guides_box = QCheckBox("Show guides (trim, spine, barcode area)")
        self.guides_box.setChecked(True)
        self.guides_box.toggled.connect(lambda _: self.refresh_preview())
        self.geometry_label = QLabel()
        self.geometry_label.setStyleSheet(f"color: {MUTED};")
        self.geometry_label.setWordWrap(True)
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(self.preview, stretch=1)
        preview_layout.addWidget(self.guides_box)
        preview_layout.addWidget(self.geometry_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.concepts_scroll)
        splitter.addWidget(self._build_form())
        splitter.addWidget(preview_panel)
        splitter.setSizes([250, 380, 620])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addLayout(top)
        layout.addWidget(splitter, stretch=1)
        self.set_status(Status.IDLE)

    def _build_form(self) -> QWidget:
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        self.title_edit, self.subtitle_edit, self.author_edit = QLineEdit(), QLineEdit(), QLineEdit()
        self.author_edit.setPlaceholderText("required - the name printed on the cover")
        self.blurb_edit = QPlainTextEdit()
        self.blurb_edit.setPlaceholderText("Back-cover text (the Illuminator writes one)")
        self.colour_edits: dict[str, QLineEdit] = {}
        self.position_combo = QComboBox()
        self.position_combo.addItem("Title at the top", "top")
        self.position_combo.addItem("Title at the bottom", "bottom")
        self.has_text_box = QCheckBox("My front art already has the title (don't draw it)")
        self.pages_spin = QSpinBox()
        self.pages_spin.setRange(0, 900)
        self.pages_spin.setSpecialValueText("estimate")
        self.save_button = QPushButton("Save && update preview")
        self.save_button.clicked.connect(lambda: self.save_requested.emit(self.current_spec()))

        form.addRow("<b>Title</b>", self.title_edit)
        form.addRow("Subtitle", self.subtitle_edit)
        form.addRow("<b>Author</b>", self.author_edit)
        form.addRow("Blurb", self.blurb_edit)
        for key, label in (("background", "Background"), ("text_color", "Title colour"), ("accent", "Subtitle colour")):
            edit = QLineEdit()
            edit.setMaximumWidth(90)
            pick = QPushButton("Pick…")
            pick.clicked.connect(lambda _=False, k=key: self._pick_colour(k))
            row = QHBoxLayout()
            row.addWidget(edit)
            row.addWidget(pick)
            row.addStretch()
            self.colour_edits[key] = edit
            form.addRow(label, row)
        form.addRow("Title position", self.position_combo)
        form.addRow("", self.has_text_box)
        form.addRow("Page count", self.pages_spin)
        form.addRow("", self.save_button)
        return form_widget

    # ---------- public ----------

    def set_cover(self, spec: CoverSpec, profile: BookProfile, book, estimated_pages: int, status: str) -> None:
        self._loading = True
        self.spec, self.profile, self.book, self.estimated_pages = spec, profile, book, estimated_pages
        self.title_edit.setText(spec.title)
        self.subtitle_edit.setText(spec.subtitle)
        self.author_edit.setText(spec.author)
        self.blurb_edit.setPlainText(spec.blurb)
        for key, edit in self.colour_edits.items():
            edit.setText(getattr(spec, key))
        self.position_combo.setCurrentIndex(max(0, self.position_combo.findData(spec.title_position)))
        self.has_text_box.setChecked(spec.art_has_text)
        self.pages_spin.setValue(spec.page_count)
        self.pages_spin.setSpecialValueText(f"estimate ({estimated_pages})")
        self._loading = False
        self._show_concepts()
        self.set_status(status)
        self.refresh_preview()

    def set_status(self, status: str) -> None:
        text, color = STATUS_TEXT.get(status, STATUS_TEXT[Status.IDLE])
        self.status_label.setText(f"<b>Cover</b> - {text}")
        self.status_label.setStyleSheet(f"color: {color};")
        busy = status == Status.RUNNING
        self.make_button.setEnabled(not busy)
        self.approve_button.setEnabled(not busy and bool(self.spec.title) and status != Status.DONE)

    def current_spec(self) -> CoverSpec:
        return replace(self.spec, title=self.title_edit.text().strip(), subtitle=self.subtitle_edit.text().strip(),
                       author=self.author_edit.text().strip(), blurb=self.blurb_edit.toPlainText().strip(),
                       title_position=self.position_combo.currentData(), art_has_text=self.has_text_box.isChecked(),
                       page_count=self.pages_spin.value(),
                       **{key: _valid_colour(edit.text(), getattr(self.spec, key))
                          for key, edit in self.colour_edits.items()})

    def refresh_preview(self) -> None:
        if self.book is None:
            self.preview.setText("No book open.")
            return
        spec = self.current_spec()
        pages = spec.page_count or self.estimated_pages
        image = render_wrap(self.book, spec, self.profile, pages, guides=self.guides_box.isChecked(),
                            scale=PREVIEW_SCALE)
        pixmap = QPixmap.fromImage(image).scaled(max(300, self.preview.width()), max(200, self.preview.height()),
                                                 Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pixmap)
        width, height = wrap_size_in(self.profile, pages)
        spine = spine_width_in(pages, self.profile.paper)
        self.geometry_label.setText(
            f"{self.profile.trim_size}\" trim, {pages} pages on {self.profile.paper} paper → spine {spine:.3f}\" · "
            f"full cover {width:.3f}\" × {height:.3f}\" incl. 0.125\" bleed"
            + ("" if pages >= SPINE_TEXT_MIN_PAGES else f" · no spine text below {SPINE_TEXT_MIN_PAGES} pages (KDP rule)"))

    # ---------- internals ----------

    def _show_concepts(self) -> None:
        panel = QWidget()
        column = QVBoxLayout(panel)
        column.setAlignment(Qt.AlignmentFlag.AlignTop)
        if not self.spec.concepts:
            column.addWidget(QLabel("No concepts yet."))
        for concept in self.spec.concepts:
            card = QFrame()
            card.setObjectName("Concept")
            chosen = concept.id == self.spec.chosen
            card.setStyleSheet(f"#Concept {{ border: 2px solid "
                               f"{STATUS_COLORS[Status.DONE] if chosen else 'rgba(128,128,128,0.4)'}; border-radius: 6px; }}")
            inner = QVBoxLayout(card)
            picture = QLabel()
            pixmap = QPixmap(str(self.book.folder / concept.art_file)) if (self.book and concept.art_file) else QPixmap()
            if not pixmap.isNull():
                thumb = pixmap.scaledToWidth(190, Qt.TransformationMode.SmoothTransformation)
                picture.setPixmap(thumb)
                picture.setFixedSize(thumb.size())
            else:
                picture.setText("(no art)")
                picture.setStyleSheet(f"background: {concept.background}; color: {concept.text_color}; padding: 30px;")
            use = QPushButton("✓ In use" if chosen else f"Use concept {concept.id}")
            use.setEnabled(not chosen)
            use.clicked.connect(lambda _=False, cid=concept.id: self.concept_chosen.emit(cid))
            inner.addWidget(picture, alignment=Qt.AlignmentFlag.AlignHCenter)
            inner.addWidget(QLabel(f"<b>{concept.id}: {concept.name}</b>"))
            inner.addWidget(use)
            card.setFixedSize(card.sizeHint())
            column.addWidget(card)
        self.concepts_scroll.setWidget(panel)

    def _pick_colour(self, key: str) -> None:
        colour = QColorDialog.getColor(QColor(self.colour_edits[key].text() or "#000000"), self, "Choose a colour")
        if colour.isValid():
            self.colour_edits[key].setText(colour.name())
            self.refresh_preview()

    def _upload(self, side: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f"Your {side} cover art", "",
                                              "Images (*.png *.jpg *.jpeg *.tif *.tiff *.webp)")
        if path:
            self.upload_requested.emit(side, Path(path))

    def resizeEvent(self, event) -> None:  # keep the preview sharp at the new size
        super().resizeEvent(event)
        if self.book is not None:
            self.refresh_preview()


def _valid_colour(text: str, fallback: str) -> str:
    return text.strip() if QColor.isValidColorName(text.strip()) else fallback
