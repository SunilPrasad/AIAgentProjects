import json

from bookguild import storage
from bookguild.config import Settings
from bookguild.events import Status
from bookguild.profile import BookProfile, load_profile, save_profile
from bookguild.ui.main_window import MainWindow


def test_each_profile_has_its_own_workspace(tmp_path):
    test_book = storage.create_book(tmp_path, "A book about tea", workspace="test")
    save_profile(test_book, BookProfile(working_title="Tea", approved=True))
    test_book.stages["profile"] = Status.DONE
    test_book.spent_usd = 0.5
    storage.save_book(test_book)

    balanced = storage.open_book(test_book.root, "balanced")
    assert balanced.folder == test_book.root / "workspaces" / "balanced"
    assert load_profile(balanced) is None  # nothing made in "test" shows in "balanced"
    assert balanced.stages["profile"] == Status.IDLE and balanced.spent_usd == 0
    assert storage.read_brief(balanced).strip() == "A book about tea"  # the brief is shared
    assert balanced.title == test_book.title  # so is the title

    again = storage.open_book(test_book.root, "test")
    assert load_profile(again).working_title == "Tea" and again.spent_usd == 0.5


def test_old_books_move_into_a_workspace(tmp_path):
    root = tmp_path / "legends"
    (root / "chapters" / "test" / "01").mkdir(parents=True)
    (root / "chapters" / "test" / "01" / "final.md").write_text("# Ch 1", encoding="utf-8")
    (root / "chapters" / "test" / "chapters.json").write_text("[]", encoding="utf-8")
    (root / "research").mkdir()
    (root / "profile.json").write_text("{}", encoding="utf-8")
    (root / "brief.md").write_text("Legends", encoding="utf-8")
    (root / "style").mkdir()
    (root / "costs.jsonl").write_text(json.dumps({"cost_usd": 0.1, "item": "test:ch01"}) + "\n", encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "title": "Legends", "created": "2026-10-27T10:00:00", "stages": {"profile": "done"}, "spent_usd": 0.79,
        "budget_usd": 5.0, "chapter_set": "test"}), encoding="utf-8")

    book = storage.open_book(root, "test")

    workspace = root / "workspaces" / "test"
    assert (workspace / "chapters" / "01" / "final.md").exists()  # chapters/test/01 flattened
    assert (workspace / "chapters.json").exists() is False and (workspace / "chapters" / "chapters.json").exists()
    assert (workspace / "profile.json").exists() and (workspace / "research").is_dir()
    assert (root / "brief.md").exists() and (root / "style").is_dir()  # shared items stay
    assert book.stages["profile"] == Status.DONE and book.spent_usd == 0.79
    assert json.loads((root / "state.json").read_text(encoding="utf-8")) == {
        "title": "Legends", "created": "2026-10-27T10:00:00"}
    assert storage.read_costs(book)[0]["item"] == "ch01"


def test_switching_profile_switches_the_open_books_workspace(tmp_path):
    settings = Settings(books_dir=tmp_path / "books", key_env_vars={"openrouter": "BG_TEST_KEY"})
    window = MainWindow(settings, settings_path=tmp_path / "settings.toml")
    book = window.create_book("A book about tea")
    save_profile(book, BookProfile(working_title="Tea"))
    window.open_book(book)
    assert window.profile_view.widgets["working_title"].text() == "Tea"

    window.set_model_profile("balanced")
    assert window.book.workspace == "balanced" and window.book.root == book.root
    assert window.profile_view.widgets["working_title"].text() == ""  # nothing from "test"
    assert window.brief_view.toPlainText().strip() == "A book about tea"
    assert "workspace: balanced" in window.book_folder_label.text()

    window.set_model_profile("test")
    assert window.profile_view.widgets["working_title"].text() == "Tea"
