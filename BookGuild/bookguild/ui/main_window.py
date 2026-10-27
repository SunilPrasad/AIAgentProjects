"""The main application window.

Layout:
    ┌ Library tree ┬ Stage timeline ······························ Cost ┐
    │ ▾ Book       ├ [Pipeline paused banner - only when paused]          │
    │   ● Steward  ├ Book page: Brief | Profile | Research | Outline |      │
    │   ▾ ● Stage  │            Chapters  (one tab per stage)              │
    │     ● Agent  ├ ▾ Log & failures (collapsible)                        │
    ├──────────────┴───────────────────────────────────────────────────────┤
    │ Chat with Steward                                                    │
    └ Status bar (API key status · model profile · web search)            ┘

The window only wires widgets to the EventBus, storage and the AI gateway.
Pipeline work lives outside the UI (stages arrive in later phases).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bookguild import storage
from bookguild.budget import Budget, format_usd
from bookguild.config import DEFAULT_SETTINGS_PATH, Settings, save_settings
from bookguild.demo import AlwaysTimeoutClient, DemoRun
from bookguild.events import EventBus, LogEntry, Status
from bookguild.gateway import AIGateway
from bookguild.llm import ModelInfo, OpenRouterClient
from bookguild.models import (
    DEFAULT_MODELS_PATH,
    SEARCH_PROVIDERS,
    ModelProfile,
    load_model_profiles,
    save_model_profiles,
)
from bookguild.reliability import CircuitBreaker, Failure, LLMError, RetryPolicy
from bookguild.chapters import chapter_cost, read_file, read_json
from bookguild.outline import load_outline, load_proposals, load_verdict
from bookguild.profile import BookProfile, load_profile
from bookguild.research.image_search import ImageSearch
from bookguild.research.search import SearchClient
from bookguild.research.sources import load_sources
from bookguild.stages import research as research_stage
from bookguild.session import BookSession
from bookguild.storage import Book
from bookguild.ui.chapters_view import ChaptersView
from bookguild.ui.chat_bar import ChatBar
from bookguild.ui.cover_view import CoverView
from bookguild.ui.failures_panel import FailuresPanel
from bookguild.ui.images_view import ImagesView
from bookguild.ui.library import LibraryPanel
from bookguild.ui.log_view import LogView
from bookguild.ui.models_dialog import ModelsDialog
from bookguild.ui.new_book_dialog import NewBookDialog
from bookguild.ui.outline_view import OutlineView
from bookguild.ui.profile_view import ProfileView
from bookguild.ui.research_view import ResearchView
from bookguild.ui.settings_dialog import SettingsDialog
from bookguild.ui.theme import MUTED, STATUS_COLORS
from bookguild.ui.timeline import StageTimeline

INVALID_TEST_KEY = "sk-or-v1-invalid-key-for-testing"


def describe_key_status(settings: Settings) -> tuple[str, bool]:
    """Return (message, ok) for the status bar."""
    missing = settings.missing_required_keys()
    if missing:
        names = ", ".join(s.env_var for s in missing)
        return f"✗ Missing required API key: set the Windows environment variable {names}", False

    openrouter_var = settings.key_env_vars["openrouter"]
    optional_found = [s.name for s in settings.key_statuses() if not s.required and s.found]
    optional_text = ", ".join(optional_found) if optional_found else "none"
    return f"✓ OpenRouter key found ({openrouter_var})   ·   optional keys found: {optional_text}", True


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, bus: EventBus | None = None,
                 settings_path: Path = DEFAULT_SETTINGS_PATH, models_path: Path = DEFAULT_MODELS_PATH):
        super().__init__()
        self.settings = settings
        self.settings_path = settings_path
        self.models_path = models_path
        self.bus = bus or EventBus()
        self.book: Book | None = None
        self.session: BookSession | None = None  # runs the pipeline for the open book
        self.demo: DemoRun | None = None

        # AI plumbing shared by every call made from this window.
        self.profiles: dict[str, ModelProfile] = load_model_profiles(models_path)
        self.client = OpenRouterClient(settings.get_key("openrouter"))
        self.breaker = CircuitBreaker()
        self.retry_policy = RetryPolicy()
        self.budget = Budget(limit_usd=storage.DEFAULT_BUDGET_USD)
        self.model_catalog: list[ModelInfo] = []
        self._tasks: set[asyncio.Task] = set()

        self.setWindowTitle("Book Guild")
        self.resize(1400, 900)

        self._build_widgets()
        self._build_menus()
        self._connect_bus()

        self.refresh_key_status()
        self.refresh_library()
        self.library.set_models(self.model_profile.model_for)

    @property
    def model_profile(self) -> ModelProfile:
        return self.profiles.get(self.settings.model_profile) or next(iter(self.profiles.values()))

    def gateway(self, client=None, budget: Budget | None = None, step_retry=None, cost_tag: str = "") -> AIGateway:
        return AIGateway(client or self.client, self.bus, budget or self.budget, self.breaker, self.retry_policy,
                         step_retry=step_retry, cost_tag=cost_tag)

    # ---------- layout ----------

    def _build_widgets(self) -> None:
        self.library = LibraryPanel()
        self.library.new_book_requested.connect(self._ask_new_book)
        self.library.book_selected.connect(self.open_book_folder)
        self.library.stage_selected.connect(self._show_stage_tab)

        self.timeline = StageTimeline()
        self.cost_label = QLabel()
        top_bar = QHBoxLayout()
        top_bar.addWidget(self.timeline, stretch=1)
        top_bar.addWidget(self.cost_label)

        self.pause_banner = self._build_pause_banner()
        self.centre = self._build_centre()

        self.log_view = LogView()
        self.failures_panel = FailuresPanel()
        self.failures_panel.retry_requested.connect(self._retry_failure)
        self.failures_panel.count_changed.connect(self._show_failure_count)
        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.addTab(self.log_view, "Log")
        self.bottom_tabs.addTab(self.failures_panel, "Failures (0)")

        self.work_splitter = QSplitter(Qt.Orientation.Vertical)
        self.work_splitter.addWidget(self.centre)
        self.work_splitter.addWidget(self._build_log_panel())
        self.work_splitter.setSizes([650, 220])
        work_splitter = self.work_splitter

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(top_bar)
        right_layout.addWidget(self.pause_banner)
        right_layout.addWidget(work_splitter)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(self.library)
        main_splitter.addWidget(right)
        main_splitter.setSizes([320, 1080])

        self.chat_bar = ChatBar()
        self.chat_bar.message_sent.connect(self._on_chat_message)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 0)
        root_layout.addWidget(main_splitter, stretch=1)
        root_layout.addWidget(self.chat_bar)
        self.setCentralWidget(root)

        self.key_status_label = QLabel()
        self.profile_label = QLabel()
        self.statusBar().addWidget(self.key_status_label)
        self.statusBar().addPermanentWidget(self.profile_label)
        self._show_cost(0.0, storage.DEFAULT_BUDGET_USD)

    def _build_log_panel(self) -> QWidget:
        """Log + Failures tabs under a slim bar that collapses them to give the book more room."""
        self.log_toggle = QPushButton("▾ Log && failures")
        self.log_toggle.setFlat(True)
        self.log_toggle.setStyleSheet("text-align: left; font-weight: bold; padding: 2px 4px;")
        self.log_toggle.clicked.connect(lambda: self.set_log_collapsed(not self.log_collapsed))
        self.log_alert = QLabel()  # failure count, visible even when collapsed
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(self.log_toggle)
        bar.addStretch()
        bar.addWidget(self.log_alert)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        layout.addWidget(self.bottom_tabs)
        self.log_panel = panel
        self.log_collapsed = False
        return panel

    def set_log_collapsed(self, collapsed: bool) -> None:
        self.log_collapsed = collapsed
        self.bottom_tabs.setVisible(not collapsed)
        self.log_toggle.setText(("▸" if collapsed else "▾") + " Log && failures")
        if collapsed:
            self.log_panel.setMaximumHeight(self.log_toggle.sizeHint().height() + 4)
        else:
            self.log_panel.setMaximumHeight(16777215)
            sizes = self.work_splitter.sizes()
            if sizes[1] < 150:
                self.work_splitter.setSizes([sum(sizes) - 220, 220])

    def _show_stage_tab(self, stage: str) -> None:
        views = {"profile": self.profile_view, "research": self.research_view, "outline": self.outline_view,
                 "chapters": self.chapters_view, "images": self.images_view, "cover": self.cover_view}
        if stage in views and self.book is not None:
            self.stage_tabs.setCurrentWidget(views[stage])

    def _build_pause_banner(self) -> QFrame:
        banner = QFrame()
        banner.setStyleSheet(f"background: {STATUS_COLORS[Status.FAILED]}; border-radius: 6px;")
        self.pause_label = QLabel()
        self.pause_label.setStyleSheet("color: white; font-weight: bold;")
        self.pause_label.setWordWrap(True)
        resume_button = QPushButton("Resume")
        resume_button.clicked.connect(self.resume_pipeline)
        layout = QHBoxLayout(banner)
        layout.addWidget(self.pause_label, stretch=1)
        layout.addWidget(resume_button)
        banner.hide()
        return banner

    def _build_centre(self) -> QStackedWidget:
        welcome = QLabel("Welcome to Book Guild\n\nCreate a new book or pick one from the library.")
        welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome.setStyleSheet(f"font-size: 18px; color: {MUTED};")

        book_page = QWidget()
        self.book_title_label = QLabel()
        self.book_title_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        self.book_folder_label = QLabel()
        self.book_folder_label.setStyleSheet(f"color: {MUTED};")
        self.book_folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        open_folder_button = QPushButton("Open book folder")
        open_folder_button.clicked.connect(self._open_book_folder_in_explorer)
        header = QHBoxLayout()
        header.addWidget(self.book_title_label)
        header.addStretch()
        header.addWidget(open_folder_button)

        self.stage_tabs = QTabWidget()  # one tab per stage view; more arrive in later phases
        self.stage_tabs.addTab(self._build_brief_tab(), "Brief")
        self.profile_view = ProfileView()
        self.profile_view.generate_requested.connect(self._generate_profile)
        self.profile_view.save_requested.connect(lambda p: self.session and self.session.save_profile(p))
        self.profile_view.approve_requested.connect(self._approve_profile)
        self.stage_tabs.addTab(self.profile_view, "Profile")
        self.research_view = ResearchView()
        self.research_view.run_requested.connect(self._run_research)
        self.research_view.exclusion_changed.connect(
            lambda source_id, excluded: self.session and self.session.set_source_excluded(source_id, excluded))
        self.stage_tabs.addTab(self.research_view, "Research")
        self.outline_view = OutlineView()
        self.outline_view.run_requested.connect(lambda: self.session and self.spawn(self.session.run_outline()))
        self.outline_view.apply_note_requested.connect(
            lambda: self.session and self.spawn(self.session.apply_chair_note()))
        self.outline_view.choose_requested.connect(
            lambda index: self.session and self.session.reply(self.session.choose_proposal(index)))
        self.outline_view.save_requested.connect(lambda o: self.session and self.session.save_outline(o))
        self.outline_view.approve_requested.connect(
            lambda o: self.session and self.session.reply(self.session.approve_outline(o)))
        self.stage_tabs.addTab(self.outline_view, "Outline")
        self.chapters_view = ChaptersView()
        self.chapters_view.loader = self._chapter_files
        self.chapters_view.write_requested.connect(lambda: self.session and self.spawn(self.session.write_chapters()))
        self.chapters_view.rewrite_requested.connect(
            lambda n: self.session and self.spawn(self.session.rewrite_chapter(n)))
        self.chapters_view.revise_requested.connect(
            lambda n, text: self.session and self.spawn(self.session.revise_chapter(n, text)))
        self.stage_tabs.addTab(self.chapters_view, "Chapters")
        self.images_view = ImagesView()
        view, run = self.images_view, self._session_call
        view.plan_requested.connect(lambda: run(lambda s: s.plan_images()))
        view.chapter_image_requested.connect(lambda number: run(lambda s: s.generate_chapter_image(number)))
        view.find_more_requested.connect(lambda slot, query: run(lambda s: s.find_more_images(slot, query)))
        view.generate_requested.connect(lambda slot: run(lambda s: s.generate_image(slot)))
        view.approve_requested.connect(lambda slot, cid: run(lambda s: s.approve_image(slot, cid)))
        view.reject_requested.connect(lambda slot, cid: self.session and self.session.reject_image(slot, cid))
        view.skip_requested.connect(lambda slot: self.session and self.session.skip_image(slot))
        view.upload_requested.connect(
            lambda slot, path: self.session and self.session.reply(self.session.upload_image(slot, path)))
        view.add_slot_requested.connect(
            lambda chapter, purpose, real: self.session and self.session.add_image_slot(chapter, purpose, real))
        self.stage_tabs.addTab(self.images_view, "Images")
        self.cover_view = CoverView()
        cover = self.cover_view
        cover.make_requested.connect(lambda: run(lambda s: s.make_cover_concepts()))
        cover.concept_chosen.connect(lambda cid: self.session and self.session.choose_cover_concept(cid))
        cover.upload_requested.connect(
            lambda side, path: self.session and self.session.reply(self.session.upload_cover_art(side, path)))
        cover.save_requested.connect(lambda spec: self.session and self.session.update_cover(spec))
        cover.approve_requested.connect(
            lambda spec: self.session and self.session.reply(self.session.approve_cover(spec)))
        self.stage_tabs.addTab(self.cover_view, "Cover")

        page_layout = QVBoxLayout(book_page)
        page_layout.addLayout(header)
        page_layout.addWidget(self.book_folder_label)
        page_layout.addWidget(self.stage_tabs, stretch=1)

        stack = QStackedWidget()
        stack.addWidget(welcome)  # index 0
        stack.addWidget(book_page)  # index 1
        return stack

    def _build_brief_tab(self) -> QWidget:
        self.brief_view = QPlainTextEdit()
        self.brief_view.textChanged.connect(lambda: self.save_brief_button.setEnabled(True))
        self.save_brief_button = QPushButton("Save brief")
        self.save_brief_button.setEnabled(False)
        self.save_brief_button.clicked.connect(self._save_brief)
        hint = QLabel("Edit your brief any time. After changing it, ask the Cartographer again to update the profile.")
        hint.setStyleSheet(f"color: {MUTED};")

        row = QHBoxLayout()
        row.addWidget(hint, stretch=1)
        row.addWidget(self.save_brief_button)
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(self.brief_view, stretch=1)
        layout.addLayout(row)
        return tab

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self._add_action(file_menu, "New book…", self._ask_new_book, QKeySequence.StandardKey.New)
        self._add_action(file_menu, "Open books folder", self._open_books_dir_in_explorer)
        self._add_action(file_menu, "Settings…", self._open_settings, "Ctrl+,")
        file_menu.addSeparator()
        self._add_action(file_menu, "Quit", self.close, QKeySequence.StandardKey.Quit)

        ai_menu = self.menuBar().addMenu("&AI")
        self._add_action(ai_menu, "Test connection", self.test_connection, "Ctrl+T")
        self._add_action(ai_menu, "Models…", self._open_models_dialog)
        profile_menu = ai_menu.addMenu("Model profile")
        self.profile_actions = QActionGroup(self)
        for name in self.profiles:
            action = self._add_action(profile_menu, name, lambda _checked=False, n=name: self.set_model_profile(n))
            action.setCheckable(True)
            action.setChecked(name == self.model_profile.name)
            self.profile_actions.addAction(action)

        dev_menu = self.menuBar().addMenu("&Developer")
        self._add_action(dev_menu, "Run demo events", self.run_demo, "Ctrl+D")
        self._add_action(dev_menu, "Reset view", self.reset_view)
        dev_menu.addSeparator()
        self._add_action(dev_menu, "Simulate: timeout (watch retries)", self.simulate_timeout)
        self._add_action(dev_menu, "Simulate: invalid API key", self.simulate_bad_key)
        self._add_action(dev_menu, "Simulate: budget reached", self.simulate_budget_reached)
        dev_menu.addSeparator()
        self._add_action(dev_menu, "Compare search providers…", self.compare_search_providers)

    def _add_action(self, menu, text, slot, shortcut=None) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _connect_bus(self) -> None:
        self.bus.log_added.connect(self._on_log_added)
        self.bus.agent_status_changed.connect(self.library.set_agent_status)
        self.bus.stage_status_changed.connect(self.timeline.set_stage_status)
        self.bus.cost_changed.connect(self._show_cost)
        self.bus.failure_added.connect(self.failures_panel.add_failure)
        self.bus.pipeline_paused.connect(self._show_paused)
        self.bus.profile_changed.connect(self._on_profile_changed)
        self.bus.steward_replied.connect(self.chat_bar.show_reply)
        self.bus.stage_status_changed.connect(self._on_stage_status)
        self.bus.research_changed.connect(self._refresh_research)
        self.bus.outline_changed.connect(self._refresh_outline)
        self.bus.chapters_changed.connect(lambda _number: self._refresh_chapters())
        self.bus.images_changed.connect(self._refresh_images)
        self.bus.cover_changed.connect(self._refresh_cover)

    # ---------- books ----------

    def refresh_library(self) -> None:
        selected = self.book.folder if self.book else None
        self.library.show_books(storage.list_books(self.settings.books_dir), selected)

    def create_book(self, brief: str, title: str = "") -> Book:
        book = storage.create_book(self.settings.books_dir, brief, title)
        self.open_book(book)
        self.refresh_library()
        self.bus.log(f"Created book '{book.title}' in {book.folder}", level="success")
        return book

    def open_book_folder(self, folder: Path) -> None:
        try:
            self.open_book(storage.open_book(folder))
        except (OSError, ValueError, KeyError) as error:
            QMessageBox.warning(self, "Cannot open book", f"Could not open {folder}:\n{error}")

    def open_book(self, book: Book) -> None:
        if self.session and self.session.busy:
            QMessageBox.information(self, "Please wait", f"Can't switch books while {self.session.busy}.")
            self.refresh_library()  # re-select the current book
            return
        self._stop_demo()
        self.book = book
        self.budget = Budget.for_book(book)
        self.session = BookSession(book, self.bus, self.gateway, lambda: self.model_profile,
                                   make_search=lambda models: SearchClient(self.settings, models.default),
                                   make_image_search=lambda: ImageSearch(self.settings))
        self._show_book_title()
        self.book_folder_label.setText(str(book.folder))
        self.brief_view.setPlainText(storage.read_brief(book))
        self.save_brief_button.setEnabled(False)
        self.profile_view.set_profile(load_profile(book), book.stages["profile"])
        self._refresh_research()
        self._refresh_outline(switch_tab=False)
        self._refresh_chapters()
        self._refresh_images()
        self._refresh_cover()
        self.stage_tabs.setCurrentWidget(self._current_stage_view(book))
        self.centre.setCurrentIndex(1)
        self.reset_view()
        self.log_view.set_entries(storage.read_log(book))

    def _show_book_title(self) -> None:
        self.setWindowTitle(f"Book Guild - {self.book.title}")
        self.book_title_label.setText(self.book.title)

    def _save_brief(self) -> None:
        if self.book:
            storage.save_brief(self.book, self.brief_view.toPlainText())
            self.save_brief_button.setEnabled(False)
            self.bus.log("Brief saved.", "success", agent="You")

    # ---------- Book Profile ----------

    def _generate_profile(self) -> None:
        if self.session:
            self.stage_tabs.setCurrentWidget(self.profile_view)
            self.spawn(self.session.generate_profile())

    def _approve_profile(self, profile) -> None:
        if self.session:
            self.session.reply(self.session.approve_profile(profile))

    def _on_stage_status(self, stage: str, status: str) -> None:
        self.library.set_stage_status(stage, status)
        if stage == "profile":
            self.profile_view.set_status(status)
        elif stage == "research":
            self.research_view.set_status(status)
        elif stage == "outline":
            self.outline_view.set_status(status)
        elif stage == "chapters":
            self._refresh_chapters()
        elif stage == "images":
            self.images_view.set_status(status)
        elif stage == "cover":
            self.cover_view.set_status(status)

    # ---------- Research ----------

    def _run_research(self) -> None:
        if self.session:
            self.spawn(self.session.run_research())

    def _refresh_research(self) -> None:
        if self.book is None:
            return
        self.research_view.set_research(load_sources(self.book), research_stage.read_topic_brief(self.book))
        self.research_view.set_status(self.book.stages["research"])

    def _current_stage_view(self, book: Book) -> QWidget:
        """The tab of the stage you're working on: the first one not yet done (the Brief for a new book)."""
        views = {"profile": self.profile_view, "research": self.research_view, "outline": self.outline_view,
                 "chapters": self.chapters_view, "images": self.images_view, "cover": self.cover_view}
        for stage, view in views.items():
            if book.stages[stage] != Status.DONE:
                return view if book.stages[stage] != Status.IDLE or stage != "profile" else self.stage_tabs.widget(0)
        return self.cover_view

    def _session_call(self, make_coroutine) -> None:
        """Run session work for a button: make_coroutine(session) -> coroutine."""
        if self.session:
            self.spawn(make_coroutine(self.session))

    def _refresh_cover(self) -> None:
        if self.book is None or self.session is None:
            return
        spec = self.session.cover()
        estimate = self.session.cover_pages(replace(spec, page_count=0))
        self.cover_view.set_cover(spec, self.session.profile or BookProfile(), self.book, estimate,
                                  self.book.stages["cover"])

    def _refresh_images(self) -> None:
        if self.book is None or self.session is None:
            return
        self.images_view.set_slots(self.session.image_slots(), self.session.profile, self.book.folder,
                                   self.book.stages["images"])

    def _refresh_chapters(self) -> None:
        if self.book is None or self.session is None:
            return
        records = self.session.chapter_records()
        costs = {r.number: chapter_cost(self.book, r.number) for r in records}
        self.chapters_view.set_records(records, self.book.stages["chapters"], costs)

    def _chapter_files(self, number: int) -> dict:
        book = self.book
        return {"final": read_file(book, number, "final.md"), "revised": read_file(book, number, "revised.md"),
                "drafts": read_json(book, number, "drafts.json"), "jury": read_json(book, number, "jury.json"),
                "factcheck": read_json(book, number, "factcheck.json"),
                "research": read_file(book, number, "research.md")}

    def _refresh_outline(self, switch_tab: bool = True) -> None:
        if self.book is None:
            return
        self.outline_view.set_data(load_outline(self.book), load_proposals(self.book), load_verdict(self.book),
                                   self.book.stages["outline"])
        if switch_tab and load_proposals(self.book):
            self.stage_tabs.setCurrentWidget(self.outline_view)
        self._show_book_title()
        self.refresh_library()

    def compare_search_providers(self) -> None:
        query, ok = QInputDialog.getText(self, "Compare search providers",
                                         "Search query (no AI writing, only searches):",
                                         text="C. V. Raman childhood and education")
        if ok and query.strip():
            self.spawn(self._compare_search_providers(query.strip()))

    async def _compare_search_providers(self, query: str) -> None:
        search = SearchClient(self.settings, self.model_profile.default)
        self.bus.log(f"Comparing search providers for: {query}", stage="research", agent="Steward")
        try:
            rows = await research_stage.compare_providers(search, query)
        finally:
            await search.close()
        for row in rows:
            if "error" in row:
                self.bus.log(f"{row['provider']}: failed - {row['error']}", "warning", "research", "Steward")
            else:
                self.bus.log(f"{row['provider']}: {row['results']} results, avg quality {row['avg_quality']}, "
                             f"{row['full_text']} with page text, {row['seconds']}s", "success", "research", "Steward")

    def _on_profile_changed(self, profile) -> None:
        if self.book is None:
            return
        self.profile_view.set_profile(profile, self.book.stages["profile"])
        self.stage_tabs.setCurrentWidget(self.profile_view)
        self._show_book_title()
        self.refresh_library()

    def reset_view(self) -> None:
        """Show the saved state of the open book (undoes anything the demo drew)."""
        self._stop_demo()
        self.library.reset_agents()
        if self.book:
            self.timeline.set_all(self.book.stages)
        else:
            self.timeline.set_all({stage: Status.IDLE for stage in storage.STAGES})
        self._show_cost(self.budget.spent_usd, self.budget.limit_usd)

    def _ask_new_book(self) -> None:
        dialog = NewBookDialog(self)
        if dialog.exec() and dialog.brief():
            self.create_book(dialog.brief(), dialog.title())

    # ---------- AI ----------

    def test_connection(self) -> None:
        """One real, tiny call with the profile's default model."""
        self.spawn(self._test_connection(self.gateway()))

    async def _test_connection(self, gateway: AIGateway) -> None:
        model = self.model_profile.default
        self.bus.log(f"Testing connection with {model}…", agent="Steward")
        result = await gateway.chat(
            agent="Steward", stage="", model=model, max_tokens=300,
            messages=[{"role": "user", "content": "Reply with exactly one word: OK"}],
        )
        self.bus.log(f"Connection OK - {result.model} replied '{result.text.strip()[:40]}' "
                     f"({result.input_tokens + result.output_tokens} tokens, ${result.cost_usd:.5f})",
                     "success", agent="Steward")

    def set_model_profile(self, name: str) -> None:
        self.settings.model_profile = name
        save_settings(self.settings, self.settings_path)
        self.library.set_models(self.model_profile.model_for)
        self.refresh_key_status()
        self.bus.log(f"Model profile set to '{name}'.", "success")

    def _open_models_dialog(self) -> None:
        dialog = ModelsDialog(self.profiles, self.model_profile.name, self.settings, self)
        dialog.accepted.connect(lambda: self._save_models(dialog.result_profiles()))
        if self.model_catalog:
            dialog.set_catalog(self.model_catalog)
        else:
            self.spawn(self._load_catalog_into(dialog))
        dialog.open()

    async def _load_catalog_into(self, dialog: ModelsDialog) -> None:
        try:
            self.model_catalog = await self.client.list_models()
        except LLMError as error:
            dialog.set_load_error(error.message)
            return
        dialog.set_catalog(self.model_catalog)

    def _save_models(self, profiles: dict[str, ModelProfile]) -> None:
        self.profiles = profiles
        save_model_profiles(profiles, self.models_path)
        self.library.set_models(self.model_profile.model_for)
        self.refresh_key_status()
        self.bus.log("Model and web search choices saved.", "success")

    def resume_pipeline(self) -> None:
        self.breaker.reset()
        self.pause_banner.hide()
        self.bus.pipeline_resumed.emit()
        self.bus.log("Pipeline resumed.", "success", agent="Steward")

    def _show_paused(self, reason: str) -> None:
        self.pause_label.setText(f"⏸ Pipeline paused - {reason}. Fix the cause, then press Resume.")
        self.pause_banner.show()

    def _retry_failure(self, failure: Failure) -> None:
        if failure.retry is not None:
            self.bus.log("Retrying…", stage=failure.stage, agent=failure.agent)
            self.spawn(failure.retry())

    def _show_failure_count(self, count: int) -> None:
        index = self.bottom_tabs.indexOf(self.failures_panel)
        self.bottom_tabs.setTabText(index, f"Failures ({count})")
        tab_bar = self.bottom_tabs.tabBar()
        color = QColor(STATUS_COLORS[Status.FAILED]) if count else tab_bar.palette().text().color()
        tab_bar.setTabTextColor(index, color)
        self.log_alert.setText(f"⚠ {count} failure(s)" if count else "")
        self.log_alert.setStyleSheet(f"color: {STATUS_COLORS[Status.FAILED]}; font-weight: bold; padding: 0 6px;")

    def spawn(self, coroutine) -> asyncio.Task:
        """Run a coroutine in the background. AI errors are already reported by the gateway."""
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._task_finished)
        return task

    def _task_finished(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None and not isinstance(error, LLMError):
            self.bus.log(f"Unexpected error: {error!r}", "error")

    # ---------- developer simulations ----------

    def simulate_timeout(self) -> None:
        self.bus.log("Simulating timeouts: expect 3 retries (2s, 4s, 8s), then FAILED.", agent="Steward")
        self.spawn(self._test_connection(self.gateway(client=AlwaysTimeoutClient())))

    def simulate_bad_key(self) -> None:
        self.bus.log("Simulating an invalid API key: expect FAILED at once with no retries.", agent="Steward")
        self.spawn(self._test_connection(self.gateway(client=OpenRouterClient(INVALID_TEST_KEY))))

    def simulate_budget_reached(self) -> None:
        self.bus.log("Simulating a used-up budget: expect FAILED before any call is made.", agent="Steward")
        self.spawn(self._test_connection(self.gateway(budget=Budget(limit_usd=0.0))))

    # ---------- events ----------

    def _on_log_added(self, entry: LogEntry) -> None:
        self.log_view.add_entry(entry)
        if self.book is None:
            return
        try:
            storage.append_log(self.book, entry)
        except OSError as error:
            self.statusBar().showMessage(f"Could not write log file: {error}", 5000)

    def _on_chat_message(self, text: str) -> None:
        if self.session is None:
            self.bus.log(text, agent="You")
            self.chat_bar.show_reply("Create a book (＋ New book) or pick one from the library first.")
            return
        self.spawn(self.session.handle_chat(text))

    def _show_cost(self, spent_usd: float, budget_usd: float) -> None:
        over_budget = spent_usd >= budget_usd
        color = STATUS_COLORS[Status.FAILED] if over_budget else ""
        self.cost_label.setText(f"Cost {format_usd(spent_usd)} / ${budget_usd:.2f}")
        self.cost_label.setStyleSheet(f"font-weight: bold; padding: 0 8px; color: {color};")

    # ---------- demo ----------

    def run_demo(self) -> None:
        self.reset_view()
        self.timeline.set_all({stage: Status.IDLE for stage in storage.STAGES})
        self.demo = DemoRun(self.bus, self.budget.limit_usd)
        self.demo.start()

    def _stop_demo(self) -> None:
        if self.demo and self.demo.is_running():
            self.demo.stop()

    # ---------- settings & folders ----------

    def refresh_key_status(self) -> None:
        message, ok = describe_key_status(self.settings)
        self.key_status_label.setText(message)
        color = STATUS_COLORS[Status.DONE] if ok else STATUS_COLORS[Status.FAILED]
        self.key_status_label.setStyleSheet(f"color: {color}; font-weight: bold; padding: 2px 6px;")
        search = SEARCH_PROVIDERS[self.model_profile.search].label
        self.profile_label.setText(f"Model profile: {self.model_profile.name}  ·  Web search: {search}  ")

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if not dialog.exec():
            return
        self.settings = dialog.result_settings()
        save_settings(self.settings, self.settings_path)
        self.client = OpenRouterClient(self.settings.get_key("openrouter"))
        self.refresh_key_status()
        self.refresh_library()
        self.bus.log("Settings saved.", level="success")

    def _open_book_folder_in_explorer(self) -> None:
        if self.book:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.book.folder)))

    def _open_books_dir_in_explorer(self) -> None:
        self.settings.books_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.settings.books_dir)))
