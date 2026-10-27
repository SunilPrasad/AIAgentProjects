"""The Profile tab: review, edit and approve the Book Profile drafted by the Cartographer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bookguild.budget import format_usd
from bookguild.events import Status
from bookguild.profile import FORMATS, IMAGE_STRATEGIES, LIMITS, MODES, PAPERS, TRIM_SIZES, VOICES, BookProfile
from bookguild.ui.theme import MUTED, STATUS_COLORS

LIST_FIELDS = ("must_include", "avoid")

STATUS_TEXT = {
    Status.IDLE: ("No profile yet - click 'Ask Cartographer' to draft one from your brief.", MUTED),
    Status.RUNNING: ("The Cartographer is working…", STATUS_COLORS[Status.RUNNING]),
    Status.WAITING: ("Draft - review and edit, then Approve.", STATUS_COLORS[Status.WAITING]),
    Status.DONE: ("Approved ✓  (editing will ask for approval again)", STATUS_COLORS[Status.DONE]),
    Status.FAILED: ("The Cartographer failed - see the Failures tab, or try again.", STATUS_COLORS[Status.FAILED]),
}


class ProfileView(QWidget):
    generate_requested = Signal()
    save_requested = Signal(object)  # BookProfile
    approve_requested = Signal(object)  # BookProfile
    style_samples_added = Signal(object)  # list[Path]
    style_sample_removed = Signal(str)  # managed relative path

    def __init__(self):
        super().__init__()
        self._loading = False  # True while filling the form from a profile (not a user edit)
        self.has_profile = False

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.generate_button = QPushButton("Ask Cartographer")
        self.generate_button.setToolTip("Draft the profile from your brief (replaces the current draft)")
        self.generate_button.clicked.connect(self.generate_requested)
        self.save_button = QPushButton("Save edits")
        self.save_button.clicked.connect(lambda: self.save_requested.emit(self.current_profile()))
        self.approve_button = QPushButton("Approve ✓")
        self.approve_button.clicked.connect(lambda: self.approve_requested.emit(self.current_profile()))

        top = QHBoxLayout()
        top.addWidget(self.status_label, stretch=1)
        top.addWidget(self.generate_button)
        top.addWidget(self.save_button)
        top.addWidget(self.approve_button)

        self.estimate_label = QLabel()
        self.estimate_label.setStyleSheet(f"color: {MUTED};")

        # Two columns of fields, so the whole profile fits without much scrolling.
        self.form_container = QWidget()
        columns = QHBoxLayout(self.form_container)
        self.left_form, self.right_form = QFormLayout(), QFormLayout()
        columns.addLayout(self.left_form, stretch=1)
        columns.addSpacing(24)
        columns.addLayout(self.right_form, stretch=1)
        self._build_fields()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form_container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.estimate_label)
        layout.addWidget(scroll, stretch=1)
        self.set_profile(None, Status.IDLE)

    # ---------- public ----------

    def set_profile(self, profile: BookProfile | None, status: str) -> None:
        self._loading = True
        has_profile = profile is not None
        profile = profile or BookProfile()
        for name, widget in self.widgets.items():
            value = getattr(profile, name)
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(max(0, widget.findData(value)))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.setValue(value)
            elif isinstance(widget, QPlainTextEdit):
                widget.setPlainText("\n".join(value) if isinstance(value, list) else value)
            else:
                widget.setText(str(value))
        for fmt, box in self.format_boxes.items():
            box.setChecked(fmt in profile.formats)
        self._loading = False

        self.has_profile = has_profile
        self.form_container.setEnabled(has_profile)
        self.save_button.setEnabled(False)
        self.generate_button.setText("Ask Cartographer again" if has_profile else "Ask Cartographer")
        self.set_status(status if has_profile or status in (Status.RUNNING, Status.FAILED) else Status.IDLE)
        self._update_estimate()

    def set_status(self, status: str) -> None:
        text, color = STATUS_TEXT.get(status, STATUS_TEXT[Status.IDLE])
        self.status_label.setText(f"<b>Book Profile</b> - {text}")
        self.status_label.setStyleSheet(f"color: {color};")
        busy = status == Status.RUNNING
        self.generate_button.setEnabled(not busy)
        self.approve_button.setEnabled(not busy and self.has_profile and status != Status.DONE)
        if busy:
            self.save_button.setEnabled(False)

    def current_profile(self) -> BookProfile:
        """The profile as currently shown in the form (validated)."""
        data = {}
        for name, widget in self.widgets.items():
            if isinstance(widget, QComboBox):
                data[name] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                data[name] = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                data[name] = widget.value()
            elif name in LIST_FIELDS:  # one item per line, so commas inside an item are safe
                data[name] = [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]
            elif isinstance(widget, QPlainTextEdit):
                data[name] = widget.toPlainText()
            else:
                data[name] = widget.text()
        data["formats"] = [fmt for fmt, box in self.format_boxes.items() if box.isChecked()]
        profile, _ = BookProfile.from_dict(data)
        return profile

    # ---------- form ----------

    def set_style_samples(self, references: list[dict[str, str]], folder: Path) -> None:
        self.sample_list.clear()
        for reference in references:
            item = QListWidgetItem(QIcon(str(folder / reference["file"])), reference["name"])
            item.setData(Qt.ItemDataRole.UserRole, reference["file"])
            self.sample_list.addItem(item)
        self.remove_sample_button.setEnabled(False)

    def _add_samples(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Book-wide image style samples", "",
                                              "Images (*.png *.jpg *.jpeg *.webp)")
        if paths:
            self.style_samples_added.emit([Path(p) for p in paths])

    def _remove_sample(self) -> None:
        item = self.sample_list.currentItem()
        if item:
            self.style_sample_removed.emit(item.data(Qt.ItemDataRole.UserRole))

    def _build_fields(self) -> None:
        self.widgets: dict[str, QWidget] = {}

        self.form = self.left_form
        self._section("What the book is")
        self._line("working_title", "Working title")
        self._line("subject", "Subject")
        self._combo("mode", "Kind of book", MODES)
        self._text("must_include", "Must include", "one topic per line")
        self._text("avoid", "Avoid", "one item per line")

        self._section("Readers & style")
        self._line("audience", "Audience")
        self._line("audience_age", "Audience age", "adult, 13-17, 9-12, 6-8, 3-5")
        self._line("reading_level", "Reading level")
        self._line("tone", "Tone")
        self._combo("voice", "Voice", VOICES)
        self._text("style_notes", "Style notes & examples")

        self.form = self.right_form
        self._section("Evidence")
        self._check("citations_required", "Citations required")
        self._check("fact_check", "Fact-check every chapter (Archivist)")

        self._section("Size & format")
        self._spin("target_pages", "Target pages")
        self._spin("words_per_page", "Words per page")
        self._spin("chapter_count", "Chapters")
        self._combo("trim_size", "Trim size (inches)", {t: t for t in TRIM_SIZES})
        self._combo("paper", "Paper", {p: p for p in PAPERS})
        formats_row = QHBoxLayout()
        self.format_boxes: dict[str, QCheckBox] = {}
        for fmt, label in FORMATS.items():
            box = QCheckBox(label)
            box.toggled.connect(self._on_edit)
            self.format_boxes[fmt] = box
            formats_row.addWidget(box)
        formats_row.addStretch()
        self.form.addRow("Formats", formats_row)

        self._section("Images")
        self._combo("image_strategy", "Image source", IMAGE_STRATEGIES)
        self._spin("images_per_chapter", "Images per chapter")
        self._text("image_style", "Book-wide image instructions",
                   "Style, colours, lighting, realism and details to use consistently throughout the book")
        samples = QWidget()
        sample_layout = QVBoxLayout(samples)
        sample_layout.setContentsMargins(0, 0, 0, 0)
        description = QLabel("Add up to 3 style samples for all AI chapter images and cover art. "
                             "Samples are saved immediately with this book and sent to the image provider "
                             "when generating. New settings apply to future generations.")
        description.setWordWrap(True)
        sample_layout.addWidget(description)
        self.sample_list = QListWidget()
        self.sample_list.setIconSize(QSize(72, 72))
        self.sample_list.setMaximumHeight(180)
        sample_layout.addWidget(self.sample_list)
        sample_buttons = QHBoxLayout()
        add_sample_button = QPushButton("Add style samples…")
        add_sample_button.clicked.connect(self._add_samples)
        self.remove_sample_button = QPushButton("Remove selected")
        self.remove_sample_button.setEnabled(False)
        self.remove_sample_button.clicked.connect(self._remove_sample)
        self.sample_list.currentRowChanged.connect(lambda row: self.remove_sample_button.setEnabled(row >= 0))
        sample_buttons.addWidget(add_sample_button)
        sample_buttons.addWidget(self.remove_sample_button)
        sample_layout.addLayout(sample_buttons)
        self.form.addRow("Style samples", samples)

        self._section("Budget")
        budget = QDoubleSpinBox()
        budget.setRange(*LIMITS["budget_usd"])
        budget.setPrefix("$ ")
        budget.setDecimals(2)
        budget.valueChanged.connect(self._on_edit)
        self._add("budget_usd", "Budget for this book", budget)

    def _section(self, title: str) -> None:
        top_gap = "<br>" if self.form.rowCount() else ""
        self.form.addRow(QLabel(f"{top_gap}<b>{title}</b>"))

    def _add(self, name: str, label: str, widget: QWidget) -> None:
        self.widgets[name] = widget
        self.form.addRow(label, widget)

    def _line(self, name: str, label: str, placeholder: str = "") -> None:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(self._on_edit)
        self._add(name, label, edit)

    def _text(self, name: str, label: str, placeholder: str = "") -> None:
        edit = QPlainTextEdit()
        edit.setPlaceholderText(placeholder)
        edit.setMaximumHeight(100)
        edit.textChanged.connect(self._on_edit)
        self._add(name, label, edit)

    def _combo(self, name: str, label: str, choices: dict[str, str]) -> None:
        combo = QComboBox()
        for value, text in choices.items():
            combo.addItem(text, value)
        combo.currentIndexChanged.connect(self._on_edit)
        self._add(name, label, combo)

    def _check(self, name: str, label: str) -> None:
        box = QCheckBox()
        box.toggled.connect(self._on_edit)
        self._add(name, label, box)

    def _spin(self, name: str, label: str) -> None:
        spin = QSpinBox()
        spin.setRange(*LIMITS[name])
        spin.valueChanged.connect(self._on_edit)
        self._add(name, label, spin)

    def _on_edit(self, *_args) -> None:
        if self._loading:
            return
        self.save_button.setEnabled(True)
        self.approve_button.setEnabled(True)
        self._update_estimate()

    def _update_estimate(self) -> None:
        p = self.current_profile()
        self.estimate_label.setText(
            f"≈ {p.target_words:,} words in total · ≈ {p.words_per_chapter:,} words per chapter · "
            f"budget {format_usd(p.budget_usd)}"
        )
