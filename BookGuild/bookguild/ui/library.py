"""The left panel: your books as a tree.

    ▾ Legends of Modern Indian Science        <- the open book (click another book to open it)
        ● Steward                               (chat)
        ▾ ● Research                            <- stage, coloured by its status; click to open its tab
            ● Scout-1   7,534 tok · $0.0012     <- agent, coloured: grey idle, blue working,
            ● Scout-2   searching 2/4                    green done, red failed
      ▸ Another book

Only the open book shows its agents (that is where work happens); other books show their stages.
Hover any agent for its full status and model.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from bookguild.events import Status
from bookguild.guild import STAGE_AGENTS
from bookguild.storage import STAGE_LABELS, STAGES, Book
from bookguild.ui.theme import STATUS_COLORS, STATUS_LABELS

ROLE = Qt.ItemDataRole.UserRole  # each item stores ("book", folder) / ("stage", stage) / ("agent", stage, agent)
GENERAL = ""  # the "stage" of agents that work outside any stage (the Steward)

_icons: dict[str, QIcon] = {}


def status_icon(status: str) -> QIcon:
    """A small filled circle in the status colour."""
    if status not in _icons:
        pixmap = QPixmap(12, 12)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(STATUS_COLORS.get(status, STATUS_COLORS[Status.IDLE])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, 10, 10)
        painter.end()
        _icons[status] = QIcon(pixmap)
    return _icons[status]


class LibraryPanel(QWidget):
    new_book_requested = Signal()
    book_selected = Signal(Path)  # the book's folder
    stage_selected = Signal(str)  # a stage of the open book was clicked

    def __init__(self):
        super().__init__()
        new_button = QPushButton("＋  New book")
        new_button.clicked.connect(self.new_book_requested)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setIndentation(14)
        self.tree.itemClicked.connect(self._on_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("<b>Library</b>"))
        layout.addWidget(new_button)
        layout.addWidget(self.tree)

        self.open_folder: Path | None = None
        self.agent_states: dict[tuple[str, str], tuple[str, str]] = {}  # (stage, agent) -> (status, detail)
        self.model_for = lambda agent: ""  # agent -> model id, for tooltips
        self.agent_items: dict[tuple[str, str], QTreeWidgetItem] = {}
        self.stage_items: dict[str, QTreeWidgetItem] = {}

    # ---------- building the tree ----------

    def show_books(self, books: list[Book], selected: Path | None = None) -> None:
        # Keep the stages you expanded open when the tree is rebuilt for the same book.
        expanded = {stage for stage, item in self.stage_items.items() if item.isExpanded()}             if selected == self.open_folder else set()
        self.open_folder = selected
        self.tree.clear()
        self.agent_items.clear()
        self.stage_items.clear()
        for book in books:
            is_open = book.folder == selected
            book_item = QTreeWidgetItem([book.title, ""])
            book_item.setData(0, ROLE, ("book", book.folder))
            book_item.setToolTip(0, str(book.folder))
            font = book_item.font(0)
            font.setBold(is_open)
            book_item.setFont(0, font)
            self.tree.addTopLevelItem(book_item)
            if is_open:
                self._add_agent(book_item, GENERAL, "Steward")
            for stage in STAGES:
                stage_item = QTreeWidgetItem([STAGE_LABELS[stage], ""])
                stage_item.setData(0, ROLE, ("stage", stage))
                stage_item.setIcon(0, status_icon(book.stages.get(stage, Status.IDLE)))
                stage_item.setToolTip(0, f"{STAGE_LABELS[stage]}: "
                                         f"{STATUS_LABELS.get(book.stages.get(stage), book.stages.get(stage))}")
                book_item.addChild(stage_item)
                if is_open:
                    self.stage_items[stage] = stage_item
                    for agent in STAGE_AGENTS[stage]:
                        self._add_agent(stage_item, stage, agent)
                    stage_item.setExpanded(stage in expanded or
                                           book.stages.get(stage) in (Status.RUNNING, Status.FAILED))
            book_item.setExpanded(is_open)
        self.tree.resizeColumnToContents(0)

    def _add_agent(self, parent: QTreeWidgetItem, stage: str, agent: str) -> None:
        item = QTreeWidgetItem([agent, ""])
        item.setData(0, ROLE, ("agent", stage, agent))
        parent.addChild(item)
        self.agent_items[(stage, agent)] = item
        status, detail = self.agent_states.get((stage, agent), (Status.IDLE, ""))
        self._paint_agent(item, stage, agent, status, detail)

    # ---------- live updates ----------

    def set_stage_status(self, stage: str, status: str) -> None:
        item = self.stage_items.get(stage)
        if item is None:
            return
        item.setIcon(0, status_icon(status))
        item.setToolTip(0, f"{STAGE_LABELS[stage]}: {STATUS_LABELS.get(status, status)}")
        if status in (Status.RUNNING, Status.FAILED):
            item.setExpanded(True)  # show the agents while they work, or when something broke

    def set_agent_status(self, agent: str, status: str, detail: str = "", stage: str = GENERAL) -> None:
        key = (stage, agent) if (stage, agent) in self.agent_items else self._find_agent(agent, stage)
        if key is None:
            return
        self.agent_states[key] = (status, detail)
        self._paint_agent(self.agent_items[key], key[0], agent, status, detail)

    def agent_status(self, stage: str, agent: str) -> str:
        return self.agent_states.get((stage, agent), (Status.IDLE, ""))[0]

    def set_models(self, model_for) -> None:
        """model_for: a function agent name -> model id (shown in tooltips)."""
        self.model_for = model_for
        for (stage, agent), item in self.agent_items.items():
            status, detail = self.agent_states.get((stage, agent), (Status.IDLE, ""))
            self._paint_agent(item, stage, agent, status, detail)

    def reset_agents(self) -> None:
        self.agent_states.clear()
        for (stage, agent), item in self.agent_items.items():
            self._paint_agent(item, stage, agent, Status.IDLE, "")

    def _find_agent(self, agent: str, stage: str) -> tuple[str, str] | None:
        """An update for a stage where the agent isn't listed: show it under any stage that lists it."""
        return next((key for key in self.agent_items if key[1] == agent), None)

    def _paint_agent(self, item: QTreeWidgetItem, stage: str, agent: str, status: str, detail: str) -> None:
        item.setIcon(0, status_icon(status))
        item.setText(1, detail or ("" if status == Status.IDLE else STATUS_LABELS.get(status, status)))
        item.setForeground(1, QColor(STATUS_COLORS[Status.FAILED] if status == Status.FAILED else "#8a8a8a"))
        font = item.font(0)
        font.setBold(status == Status.RUNNING)
        item.setFont(0, font)
        model = self.model_for(agent)
        tip = f"{agent}: {STATUS_LABELS.get(status, status)}" + (f"\n{detail}" if detail else "") + \
            (f"\nmodel: {model}" if model else "")
        item.setToolTip(0, tip)
        item.setToolTip(1, tip)

    # ---------- clicks ----------

    def _on_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, ROLE)
        book_item = item
        while book_item.parent() is not None:
            book_item = book_item.parent()
        folder = book_item.data(0, ROLE)[1]
        if folder != self.open_folder:
            self.book_selected.emit(folder)
        if data and data[0] in ("stage", "agent") and data[1]:
            self.stage_selected.emit(data[1])
