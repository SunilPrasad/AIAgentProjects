import json

import pytest

from bookguild import storage
from bookguild.events import LogEntry, Status


def test_create_book_makes_folder_with_state(tmp_path):
    book = storage.create_book(tmp_path, "The History of Tea!")

    assert book.folder == tmp_path / "the-history-of-tea"
    state = json.loads((book.folder / "state.json").read_text(encoding="utf-8"))
    assert state["title"] == "The History of Tea!"
    assert state["stages"] == {stage: Status.IDLE for stage in storage.STAGES}
    assert "folder" not in state


def test_same_title_gets_unique_folder(tmp_path):
    first = storage.create_book(tmp_path, "Tea")
    second = storage.create_book(tmp_path, "Tea")

    assert first.folder.name == "tea"
    assert second.folder.name == "tea-2"


def test_empty_title_rejected(tmp_path):
    with pytest.raises(ValueError):
        storage.create_book(tmp_path, "   ")


def test_state_round_trip(tmp_path):
    book = storage.create_book(tmp_path, "Tea")
    book.stages["research"] = Status.DONE
    book.spent_usd = 1.25
    storage.save_book(book)

    reopened = storage.open_book(book.folder)
    assert reopened.stages["research"] == Status.DONE
    assert reopened.spent_usd == 1.25


def test_list_books_skips_broken_folders(tmp_path):
    storage.create_book(tmp_path, "Good book")
    (tmp_path / "not-a-book").mkdir()
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "state.json").write_text("{ not json", encoding="utf-8")

    assert [b.title for b in storage.list_books(tmp_path)] == ["Good book"]
    assert storage.list_books(tmp_path / "missing") == []


def test_log_append_and_read_skips_corrupt_lines(tmp_path):
    book = storage.create_book(tmp_path, "Tea")
    storage.append_log(book, LogEntry("first", agent="Scout-1", stage="research"))
    with open(book.folder / "log.jsonl", "a", encoding="utf-8") as f:
        f.write("garbage line\n")
    storage.append_log(book, LogEntry("second", level="error"))

    entries = storage.read_log(book)
    assert [e.message for e in entries] == ["first", "second"]
    assert entries[0].agent == "Scout-1"
    assert storage.read_log(book, limit=1)[0].message == "second"


def test_brief_is_saved_and_title_is_optional(tmp_path):
    brief = "A researched book on the history of tea for adults.\nTone: story-driven, sourced."
    book = storage.create_book(tmp_path, brief)

    assert storage.read_brief(book).strip() == brief
    assert book.title == "A researched book on the history of tea for adults."


def test_explicit_title_wins_over_brief(tmp_path):
    book = storage.create_book(tmp_path, "Some long idea about tea", title="Leaves of Empire")
    assert book.title == "Leaves of Empire"
    assert book.folder.name == "leaves-of-empire"


def test_provisional_title_is_shortened_at_a_word():
    brief = "\n\n  " + "word " * 40
    title = storage.provisional_title(brief)
    assert len(title) <= 61 and title.endswith("…") and not title.startswith(" ")
