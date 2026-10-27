"""The chat bar at the bottom: where you talk to the Steward.

The Steward's latest answer is shown just above the input; the full conversation is in the log.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from bookguild.ui.theme import STATUS_COLORS


class ChatBar(QWidget):
    message_sent = Signal(str)

    def __init__(self):
        super().__init__()
        self.reply_label = QLabel()
        self.reply_label.setWordWrap(True)
        self.reply_label.setStyleSheet(f"color: {STATUS_COLORS['running']}; padding: 2px 4px;")
        self.reply_label.hide()

        self.input = QLineEdit()
        self.input.setPlaceholderText("Talk to the Steward…  e.g. \"draft the profile\", \"make it for teenagers\", "
                                      "\"approve\", \"cost\", \"help\"")
        self.input.returnPressed.connect(self._send)

        send_button = QPushButton("Send")
        send_button.clicked.connect(self._send)

        row = QHBoxLayout()
        row.addWidget(QLabel("<b>Steward ▸</b>"))
        row.addWidget(self.input, stretch=1)
        row.addWidget(send_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 4)
        layout.setSpacing(2)
        layout.addWidget(self.reply_label)
        layout.addLayout(row)

    def show_reply(self, text: str) -> None:
        self.reply_label.setText(f"<b>Steward:</b> {text}")
        self.reply_label.show()

    def _send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.message_sent.emit(text)
