"""New Book dialog: you describe your idea in your own words. The title is optional."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from bookguild.ui.theme import MUTED

BRIEF_PLACEHOLDER = """Describe the book in your own words. For example:

A well-researched book on the history of tea for curious adult readers.
Cover where tea came from in China, how it spread along trade routes, the British tea trade,
the Opium Wars, and tea culture today in India, Japan and Britain.
Tone: engaging and story-driven, like "Salt" by Mark Kurlansky, but every fact must be sourced.
About 100 pages, 6x9 paperback, with historical images (maps, old paintings).

Example chapter I like: "The Emperor and the Leaf" - opening with the legend of Shennong,
then separating legend from what archaeology actually shows."""


class NewBookDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("New book")
        self.resize(720, 560)

        intro = QLabel(
            "<b>Your brief</b> - the idea, audience, style, examples you like, anything that matters. "
            "The Guild reads this first, and the Cartographer turns it into a Book Profile you can review."
        )
        intro.setWordWrap(True)

        self.brief_edit = QPlainTextEdit()
        self.brief_edit.setPlaceholderText(BRIEF_PLACEHOLDER)
        self.brief_edit.textChanged.connect(self._update_ok_button)

        title_label = QLabel(
            f"<b>Working title</b> <span style='color:{MUTED}'>(optional - leave blank and the "
            "Architects will propose titles)</span>"
        )
        self.title_edit = QLineEdit()

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create book")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.brief_edit, stretch=1)
        layout.addWidget(title_label)
        layout.addWidget(self.title_edit)
        layout.addWidget(self.buttons)
        self._update_ok_button()

    def brief(self) -> str:
        return self.brief_edit.toPlainText().strip()

    def title(self) -> str:
        return self.title_edit.text().strip()

    def _update_ok_button(self) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.brief()))
