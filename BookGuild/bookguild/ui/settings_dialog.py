"""Settings dialog: the books folder and the names of the API key environment variables.

Key values are never shown here, only whether each variable was found.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bookguild.config import REQUIRED_KEYS, Settings, read_env_var
from bookguild.ui.theme import STATUS_COLORS


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)
        self.model_profile = settings.model_profile  # edited in AI > Model profile, not here
        self.contact = settings.contact  # edited in settings.toml

        self.books_dir_edit = QLineEdit(str(settings.books_dir))
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse)
        books_row = QHBoxLayout()
        books_row.addWidget(self.books_dir_edit)
        books_row.addWidget(browse_button)

        form = QFormLayout()
        form.addRow("Books folder:", books_row)
        form.addRow(QLabel("<br><b>API keys</b> - environment variable names (values are never shown)"))

        self.key_edits: dict[str, QLineEdit] = {}
        self.key_status_labels: dict[str, QLabel] = {}
        for name, env_var in settings.key_env_vars.items():
            edit = QLineEdit(env_var)
            status = QLabel()
            edit.textChanged.connect(lambda _text, n=name: self._refresh_status(n))
            self.key_edits[name] = edit
            self.key_status_labels[name] = status
            row = QHBoxLayout()
            row.addWidget(edit)
            row.addWidget(status)
            label = f"{name} (required):" if name in REQUIRED_KEYS else f"{name}:"
            form.addRow(label, row)
            self._refresh_status(name)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def result_settings(self) -> Settings:
        """The settings as edited in the dialog."""
        return Settings(
            books_dir=Path(self.books_dir_edit.text().strip()).expanduser(),
            key_env_vars={name: edit.text().strip() for name, edit in self.key_edits.items()},
            model_profile=self.model_profile,
            contact=self.contact,
        )

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose books folder", self.books_dir_edit.text())
        if folder:
            self.books_dir_edit.setText(folder)

    def _refresh_status(self, name: str) -> None:
        env_var = self.key_edits[name].text().strip()
        found = bool(env_var) and read_env_var(env_var) is not None
        label = self.key_status_labels[name]
        if found:
            label.setText(f"<span style='color:{STATUS_COLORS['done']}'>✓ found</span>")
        else:
            color = STATUS_COLORS["failed"] if name in REQUIRED_KEYS else "#8a8a8a"
            label.setText(f"<span style='color:{color}'>✗ not set</span>")
