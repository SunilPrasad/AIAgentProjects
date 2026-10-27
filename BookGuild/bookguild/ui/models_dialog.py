"""AI > Models...: choose the OpenRouter model for each Guild role (with live prices)
and the web search provider the Scouts use.

Saving is blocked while the provider-diversity rules are broken.
"""

from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from bookguild.config import Settings
from bookguild.llm import ModelInfo
from bookguild.models import SCHOLARLY_SOURCES, SEARCH_PROVIDERS, ModelProfile, diversity_problems
from bookguild.ui.theme import MUTED, STATUS_COLORS


def role_rows(profile: ModelProfile) -> list[tuple[str, str]]:
    """(key, label) for every model slot in a profile. Keys look like 'chair' or 'scribes.1'."""
    rows = [("default", "Default (Steward, Cartographer, Scouts…)")]
    rows += [(f"scribes.{i}", f"Scribe-{i + 1} / Architect-{i + 1}") for i in range(len(profile.scribes))]
    rows += [(f"jurors.{i}", f"Juror-{i + 1}") for i in range(len(profile.jurors))]
    rows += [("chair", "Council Chair"), ("archivist", "Archivist"), ("image", "Image generation"),
             ("cover_image", "Cover art (2K)"), ("fallback", "Fallback")]
    return rows


def get_slot(profile: ModelProfile, key: str) -> str:
    name, _, index = key.partition(".")
    value = getattr(profile, name)
    return value[int(index)] if index else value


def set_slot(profile: ModelProfile, key: str, model_id: str) -> None:
    name, _, index = key.partition(".")
    if index:
        getattr(profile, name)[int(index)] = model_id
    else:
        setattr(profile, name, model_id)


class ModelsDialog(QDialog):
    def __init__(self, profiles: dict[str, ModelProfile], active: str, settings: Settings | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Models & web search")
        self.resize(780, 680)
        self.profiles = copy.deepcopy(profiles)  # edited copy; the caller saves it on accept
        self.settings = settings  # used only to show whether search API keys are set
        self.catalog: dict[str, ModelInfo] = {}
        self.combos: dict[str, QComboBox] = {}
        self.price_labels: dict[str, QLabel] = {}
        self.search_combos: dict[str, QComboBox] = {}  # "search" / "search_fallback"
        self.search_notes: dict[str, QLabel] = {}

        self.profile_combo = QComboBox()
        self.profile_combo.addItems(list(self.profiles))
        self.profile_combo.setCurrentText(active)
        self.profile_combo.currentTextChanged.connect(self._show_profile)
        self.current_name = active

        self.status_label = QLabel("Loading model list and prices from OpenRouter…")
        self.status_label.setStyleSheet(f"color: {MUTED};")
        self.form = QFormLayout()
        self.problems_label = QLabel()
        self.problems_label.setWordWrap(True)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        top = QHBoxLayout()
        top.addWidget(QLabel("Editing profile:"))
        top.addWidget(self.profile_combo)
        top.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.status_label)
        layout.addLayout(self.form)
        layout.addWidget(self.problems_label)
        layout.addStretch()
        layout.addWidget(self.buttons)
        self._show_profile(active)

    def set_catalog(self, models: list[ModelInfo]) -> None:
        self.catalog = {m.id: m for m in models}
        self.status_label.setText(f"{len(models)} models available. Prices are USD per million tokens (in / out).")
        self._show_profile(self.current_name)

    def set_load_error(self, message: str) -> None:
        self.status_label.setText(f"Could not load the model list ({message}). You can still type model ids.")
        self.status_label.setStyleSheet(f"color: {STATUS_COLORS['failed']};")

    def result_profiles(self) -> dict[str, ModelProfile]:
        self._store_edits()
        return self.profiles

    # ---------- internals ----------

    def _show_profile(self, name: str) -> None:
        if self.combos:
            self._store_edits()
        self.current_name = name
        while self.form.rowCount():
            self.form.removeRow(0)
        self.combos.clear()
        self.price_labels.clear()

        profile = self.profiles[name]
        for key, label in role_rows(profile):
            combo = self._model_combo(images=key in ("image", "cover_image"))
            combo.setCurrentText(get_slot(profile, key))
            price = QLabel()
            price.setMinimumWidth(150)
            combo.currentTextChanged.connect(lambda _text, k=key: self._on_edit(k))
            self.combos[key] = combo
            self.price_labels[key] = price
            row = QHBoxLayout()
            row.addWidget(combo, stretch=1)
            row.addWidget(price)
            self.form.addRow(label, row)
            self._update_price(key)

        self._add_search_rows(profile)
        self._update_problems()

    def _add_search_rows(self, profile: ModelProfile) -> None:
        self.search_combos.clear()
        self.search_notes.clear()
        self.form.addRow(QLabel("<br><b>Web research (Scouts)</b>"))
        for key, label in (("search", "Web search"), ("search_fallback", "Search fallback")):
            combo = QComboBox()
            for provider in SEARCH_PROVIDERS.values():
                combo.addItem(provider.label, provider.id)
            combo.setCurrentIndex(max(0, combo.findData(getattr(profile, key))))
            note = QLabel()
            note.setWordWrap(True)
            combo.currentIndexChanged.connect(lambda _i, k=key: self._on_search_edit(k))
            self.search_combos[key] = combo
            self.search_notes[key] = note
            self.form.addRow(label, combo)
            self.form.addRow("", note)
            self._update_search_note(key)

        scholarly = QLabel(f"Always added for evidence books (free): {', '.join(SCHOLARLY_SOURCES)}")
        scholarly.setStyleSheet(f"color: {MUTED};")
        self.form.addRow("", scholarly)

    def _on_search_edit(self, key: str) -> None:
        self._update_search_note(key)
        self._store_edits()
        self._update_problems()

    def _update_search_note(self, key: str) -> None:
        provider = SEARCH_PROVIDERS[self.search_combos[key].currentData()]
        text = provider.cost_note
        color = MUTED
        if provider.key_name is None:
            text += "  ✓ no key needed"
        elif self.settings is not None:
            env_var = self.settings.key_env_vars.get(provider.key_name, provider.key_name)
            if self.settings.get_key(provider.key_name):
                text += f"  ✓ {env_var} found"
            else:
                text += f"  ✗ {env_var} not set - the fallback will be used"
                color = STATUS_COLORS["waiting"]
        note = self.search_notes[key]
        note.setText(text)
        note.setStyleSheet(f"color: {color};")

    def _model_combo(self, images: bool) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        ids = sorted(m.id for m in self.catalog.values() if m.makes_images or not images)
        combo.addItems(ids)
        completer = QCompleter(ids, combo)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        combo.setCompleter(completer)
        return combo

    def _on_edit(self, key: str) -> None:
        self._update_price(key)
        self._store_edits()
        self._update_problems()

    def _store_edits(self) -> None:
        profile = self.profiles[self.current_name]
        for key, combo in self.combos.items():
            set_slot(profile, key, combo.currentText().strip())
        for key, combo in self.search_combos.items():
            setattr(profile, key, combo.currentData())

    def _update_price(self, key: str) -> None:
        model_id = self.combos[key].currentText().strip()
        info = self.catalog.get(model_id)
        label = self.price_labels[key]
        if info:
            label.setText(f"${info.input_per_m:.3f} / ${info.output_per_m:.3f}")
            label.setStyleSheet(f"color: {MUTED};")
        elif self.catalog:
            label.setText("unknown model")
            label.setStyleSheet(f"color: {STATUS_COLORS['failed']};")
        else:
            label.setText("")

    def _update_problems(self) -> None:
        all_problems = {name: diversity_problems(p) for name, p in self.profiles.items()}
        current = all_problems[self.current_name]
        others = [name for name, problems in all_problems.items() if problems and name != self.current_name]
        if current or others:
            lines = [f"⚠ {p}" for p in current] + [f"⚠ Profile '{n}' also has problems." for n in others]
            self.problems_label.setText("\n".join(lines))
            self.problems_label.setStyleSheet(f"color: {STATUS_COLORS['failed']};")
        else:
            self.problems_label.setText("✓ Diversity rules OK: each Scribe has its own provider; "
                                        "the Council shares no provider with the Scribes.")
            self.problems_label.setStyleSheet(f"color: {STATUS_COLORS['done']};")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(not (current or others))
