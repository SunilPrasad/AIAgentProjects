import pytest

from bookguild import prompts, storage
from bookguild.profile import BookProfile, load_profile, save_profile


def test_messy_model_output_is_cleaned_with_warnings():
    profile, warnings = BookProfile.from_dict({
        "mode": "Evidence",
        "trim_size": "6 x 9",
        "image_strategy": "licensed web",
        "target_pages": "5000",
        "chapter_count": "twelve",
        "citations_required": "yes",
        "must_include": "Shennong legend, Opium Wars",
        "voice": "omniscient",
        "unknown_key": "ignored",
    })

    assert profile.mode == "evidence"
    assert profile.trim_size == "6x9"
    assert profile.image_strategy == "licensed_web"
    assert profile.target_pages == 800  # clamped
    assert profile.chapter_count == 10  # default kept
    assert profile.citations_required is True
    assert profile.must_include == ["Shennong legend", "Opium Wars"]
    assert profile.voice == "third"
    assert len(warnings) == 3  # pages clamped, chapters not a number, unknown voice


def test_mode_sets_sensible_defaults():
    profile, _ = BookProfile.from_dict({"mode": "children"})
    assert profile.trim_size == "8.5x8.5"
    assert profile.image_strategy == "ai_generated"
    assert profile.citations_required is False


def test_no_images_means_zero_images_per_chapter():
    profile, _ = BookProfile.from_dict({"image_strategy": "none", "images_per_chapter": 5})
    assert profile.images_per_chapter == 0


def test_not_a_dict_gives_defaults():
    profile, warnings = BookProfile.from_dict(["not", "a", "dict"])
    assert profile == BookProfile()
    assert warnings


def test_estimates():
    profile = BookProfile(target_pages=100, words_per_page=250, chapter_count=10)
    assert profile.target_words == 25_000
    assert profile.words_per_chapter == 2_500


def test_save_and_load(tmp_path):
    book = storage.create_book(tmp_path, "Tea")
    assert load_profile(book) is None
    save_profile(book, BookProfile(working_title="Leaves", approved=True))

    loaded = load_profile(book)
    assert loaded.working_title == "Leaves" and loaded.approved


def test_prompt_rendering():
    text = prompts.render("cartographer", brief="A book about tea")
    assert "A book about tea" in text and "{{" not in text
    with pytest.raises(KeyError):
        prompts.render("cartographer")


def test_normalize_age():
    from bookguild.profile import normalize_age

    assert normalize_age("teenagers_13_17") == "13-17"
    assert normalize_age("Adults") == "adult"
    assert normalize_age("8+") == "8+"
    assert normalize_age("") == "adult"
