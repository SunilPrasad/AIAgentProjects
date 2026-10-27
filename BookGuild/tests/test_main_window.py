from bookguild import config, storage
from bookguild.config import Settings, load_settings
from bookguild.demo import DEMO_STEPS
from bookguild.events import Status
from bookguild.ui.main_window import MainWindow

KEY_VAR = "BOOKGUILD_TEST_OPENROUTER_KEY"


def make_window(tmp_path) -> MainWindow:
    settings = Settings(books_dir=tmp_path / "books", key_env_vars={"openrouter": KEY_VAR})
    return MainWindow(settings, settings_path=tmp_path / "settings.toml")


def test_window_shows_key_found(tmp_path, monkeypatch):
    monkeypatch.setenv(KEY_VAR, "sk-or-secret-value")
    window = make_window(tmp_path)

    text = window.key_status_label.text()
    assert "OpenRouter key found" in text
    assert "sk-or-secret-value" not in text


def test_window_shows_red_error_when_key_missing(tmp_path, monkeypatch):
    monkeypatch.delenv(KEY_VAR, raising=False)
    monkeypatch.setattr(config, "_read_windows_registry_env", lambda env_var: None)
    window = make_window(tmp_path)

    assert "Missing required API key" in window.key_status_label.text()
    assert "#c62828" in window.key_status_label.styleSheet()


def test_create_book_shows_it_and_writes_log(tmp_path):
    window = make_window(tmp_path)
    book = window.create_book("History of Tea")

    assert book.folder.is_dir()
    assert window.library.tree.topLevelItemCount() == 1
    assert window.centre.currentIndex() == 1
    assert "History of Tea" in window.windowTitle()
    assert any("Created book" in e.message for e in storage.read_log(book))


def test_chat_message_is_logged(tmp_path):
    import asyncio

    window = make_window(tmp_path)
    book = window.create_book("Tea")
    asyncio.run(window.session.handle_chat("help"))

    agents = [e.agent for e in storage.read_log(book)]
    assert "You" in agents and "Steward" in agents
    assert "draft the profile" in window.chat_bar.reply_label.text()


def test_chat_without_book_asks_to_create_one(tmp_path):
    window = make_window(tmp_path)
    window.chat_bar.input.setText("hello")
    window.chat_bar.input.returnPressed.emit()
    assert "New book" in window.chat_bar.reply_label.text()


def test_bus_events_update_board_timeline_and_cost(tmp_path):
    window = make_window(tmp_path)
    window.create_book("Tea")
    window.bus.set_agent_status("Scout-2", Status.FAILED, "timeout", "research")
    window.bus.set_stage_status("research", Status.RUNNING)
    window.bus.set_cost(1.5, 5.0)

    assert window.library.agent_status("research", "Scout-2") == Status.FAILED
    assert window.library.agent_status("chapters", "Scout-2") == Status.IDLE  # same Scout, other stage
    assert window.library.stage_items["research"].isExpanded()
    assert window.timeline.chips["research"].property("status") == Status.RUNNING
    assert window.cost_label.text() == "Cost $1.50 / $5.00"


def test_demo_runs_all_steps_and_reset_restores_saved_state(tmp_path):
    window = make_window(tmp_path)
    window.create_book("Tea")
    window.run_demo()
    for _ in DEMO_STEPS:
        window.demo._next_step()

    assert window.timeline.chips["outline"].property("status") == Status.WAITING
    assert window.library.agent_status("research", "Scout-2") == Status.FAILED

    window.reset_view()
    assert window.timeline.chips["outline"].property("status") == Status.IDLE
    assert window.library.agent_status("research", "Scout-2") == Status.IDLE


def test_settings_save_round_trip(tmp_path):
    path = tmp_path / "settings.toml"
    original = Settings(books_dir=tmp_path / "my books", key_env_vars={"openrouter": "MY_OR_KEY", "tavily": "T"})
    config.save_settings(original, path)

    loaded = load_settings(path)
    assert loaded.books_dir == original.books_dir
    assert loaded.key_env_vars == original.key_env_vars


def test_new_book_dialog_needs_a_brief():
    from PySide6.QtWidgets import QDialogButtonBox

    from bookguild.ui.new_book_dialog import NewBookDialog

    dialog = NewBookDialog()
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()

    dialog.brief_edit.setPlainText("A book about tea\nwith examples")
    assert ok.isEnabled()
    assert dialog.title() == ""


def test_book_page_shows_brief(tmp_path):
    window = make_window(tmp_path)
    window.create_book("A book about tea\nFor adults, with sources.", title="Tea")
    assert "For adults, with sources." in window.brief_view.toPlainText()


def test_failures_panel_counts_and_resolves(tmp_path):
    from bookguild.reliability import Failure

    window = make_window(tmp_path)
    failure = Failure(stage="research", agent="Scout-1", model="m/x", error="boom", kind="transient", attempts=4)
    window.bus.failure_added.emit(failure)

    tab_text = window.bottom_tabs.tabText(window.bottom_tabs.indexOf(window.failures_panel))
    assert tab_text == "Failures (1)"
    window.failures_panel.resolve(failure.id)
    assert window.failures_panel.table.rowCount() == 0


def test_pause_banner_and_resume(tmp_path):
    window = make_window(tmp_path)
    window.show()
    window.bus.pipeline_paused.emit("3 calls failed in a row")
    assert window.pause_banner.isVisible()

    window.breaker.consecutive_failures = 3
    window.resume_pipeline()
    assert not window.pause_banner.isVisible()
    assert not window.breaker.is_open


def test_switching_model_profile_is_saved(tmp_path):
    window = make_window(tmp_path)
    window.set_model_profile("balanced")

    assert load_settings(tmp_path / "settings.toml").model_profile == "balanced"
    window.create_book("Tea")
    scribe_item = window.library.agent_items[("chapters", "Scribe-1")]
    assert window.profiles["balanced"].scribes[0] in scribe_item.toolTip(0)


def test_models_dialog_blocks_save_when_rules_broken(tmp_path):
    from PySide6.QtWidgets import QDialogButtonBox

    from bookguild.ui.models_dialog import ModelsDialog

    window = make_window(tmp_path)
    dialog = ModelsDialog(window.profiles, "test")
    save = dialog.buttons.button(QDialogButtonBox.StandardButton.Save)
    assert save.isEnabled()

    dialog.combos["chair"].setCurrentText(window.profiles["test"].scribes[0])
    assert not save.isEnabled()
    assert "shares provider" in dialog.problems_label.text()


def test_models_dialog_edits_search_provider(tmp_path, monkeypatch):
    from bookguild.ui.models_dialog import ModelsDialog

    monkeypatch.delenv("BOOKGUILD_TEST_TAVILY", raising=False)
    monkeypatch.setattr(config, "_read_windows_registry_env", lambda env_var: None)
    window = make_window(tmp_path)
    settings = Settings(books_dir=tmp_path, key_env_vars={"openrouter": KEY_VAR, "tavily": "BOOKGUILD_TEST_TAVILY"})
    dialog = ModelsDialog(window.profiles, "test", settings)

    combo = dialog.search_combos["search"]
    combo.setCurrentIndex(combo.findData("tavily"))
    assert "BOOKGUILD_TEST_TAVILY not set" in dialog.search_notes["search"].text()
    assert dialog.result_profiles()["test"].search == "tavily"
    assert "Web search: Exa via OpenRouter" in window.profile_label.text()


def test_profile_tab_save_and_approve(tmp_path):
    from bookguild.profile import BookProfile, load_profile, save_profile

    window = make_window(tmp_path)
    book = window.create_book("Tea")
    save_profile(book, BookProfile(working_title="Leaves"))
    window.open_book(book)

    view = window.profile_view
    assert view.widgets["working_title"].text() == "Leaves"
    view.widgets["target_pages"].setValue(140)
    assert view.save_button.isEnabled()

    view.approve_button.click()
    saved = load_profile(book)
    assert saved.target_pages == 140 and saved.approved
    assert window.timeline.chips["profile"].property("status") == Status.DONE
    assert not view.approve_button.isEnabled()
    assert window.book_title_label.text() == "Leaves"


def test_profile_list_fields_keep_commas_inside_items(tmp_path):
    from bookguild.profile import BookProfile, load_profile, save_profile

    window = make_window(tmp_path)
    book = window.create_book("Tea")
    save_profile(book, BookProfile(must_include=["Childhood, dreams, and struggles", "Discoveries"]))
    window.open_book(book)

    assert window.profile_view.widgets["must_include"].toPlainText() == "Childhood, dreams, and struggles\nDiscoveries"
    window.profile_view.save_button.setEnabled(True)
    window.profile_view.save_button.click()
    assert load_profile(book).must_include == ["Childhood, dreams, and struggles", "Discoveries"]


def test_outline_view_round_trip_and_reorder():
    from bookguild.outline import ChapterPlan, Outline, Proposal
    from bookguild.ui.outline_view import OutlineView

    view = OutlineView()
    outline = Outline("Legends", "sub", "pitch", [ChapterPlan("Raman", "light", ["prism", "sea"], ["S1", "S4"]),
                                                   ChapterPlan("Bose", "plants")])
    verdict = {"winner": 0, "points": {"0": 4, "1": 2}, "weighted": {"0": 8.1, "1": 6.0}, "chair_note": "- more",
               "ballots": [{"juror": "Juror-1", "reasons": {"0": "strong", "1": "thin"}}], "failed_jurors": []}
    view.set_data(outline, [Proposal("Architect-1", "m1", outline), Proposal("Architect-2", "m2", outline)],
                  verdict, Status.WAITING)

    assert len(view.cards) == 2 and "Council's choice" in view.cards[0].header.text()
    assert view.current_outline().chapters[0].key_points == ["prism", "sea"]
    view.table.setCurrentCell(1, 0)
    view._move(-1)
    assert [c.title for c in view.current_outline().chapters] == ["Bose", "Raman"]
    assert view.save_button.isEnabled() and view.approve_button.isEnabled()


def test_library_tree_shows_stages_and_agents_of_the_open_book(tmp_path):
    window = make_window(tmp_path)
    first = window.create_book("First book")
    window.create_book("Second book")  # now open
    tree = window.library.tree
    assert tree.topLevelItemCount() == 2
    titles = [tree.topLevelItem(i).text(0) for i in range(2)]
    open_item = tree.topLevelItem(titles.index("Second book"))
    other_item = tree.topLevelItem(titles.index("First book"))
    assert open_item.isExpanded() and open_item.child(0).text(0) == "Steward"
    assert open_item.childCount() == 8  # Steward + 7 stages
    outline = next(open_item.child(i) for i in range(open_item.childCount()) if open_item.child(i).text(0) == "Outline")
    assert [outline.child(i).text(0) for i in range(outline.childCount())][:3] == ["Architect-1", "Architect-2",
                                                                                   "Architect-3"]
    assert other_item.childCount() == 7 and other_item.child(0).childCount() == 0  # no agents for closed books

    window.library._on_clicked(other_item, 0)  # clicking another book opens it
    assert window.book.folder == first.folder


def test_clicking_a_stage_opens_its_tab(tmp_path):
    window = make_window(tmp_path)
    window.create_book("Tea")
    window.library._on_clicked(window.library.stage_items["research"], 0)
    assert window.stage_tabs.currentWidget() is window.research_view


def test_log_collapses_and_shows_failure_count(tmp_path):
    from bookguild.reliability import Failure

    window = make_window(tmp_path)
    window.show()
    window.set_log_collapsed(True)
    assert not window.bottom_tabs.isVisible()
    window.bus.failure_added.emit(Failure(stage="", agent="Steward", model="m", error="x", kind="permanent",
                                          attempts=1))
    assert "1 failure" in window.log_alert.text()
    window.set_log_collapsed(False)
    assert window.bottom_tabs.isVisible()
