import asyncio
import base64
import json

import httpx
import pytest
from PySide6.QtGui import QImage

from bookguild import storage
from bookguild.image_style import add_reference, load_references, reference_data_urls, remove_reference
from bookguild.llm import LLMResult, OpenRouterClient
from bookguild.profile import save_profile
from bookguild.reliability import PermanentError, TransientError
from tests.test_images import make_session, png_bytes


def test_samples_are_portable_resized_and_originals_preserved(tmp_path):
    book = storage.create_book(tmp_path, "Style")
    source = tmp_path / "sample.png"
    source.write_bytes(png_bytes(3000, 2000))
    add_reference(book, source)
    saved = load_references(book)
    path = book.folder / saved[0]["file"]
    assert QImage(str(path)).width() == 1024
    assert saved[0]["name"] == source.name
    assert reference_data_urls(book)[0].startswith("data:image/png;base64,")
    reopened = storage.open_book(book.folder)
    assert load_references(reopened) == saved
    remove_reference(reopened, saved[0]["file"])
    assert source.exists() and not path.exists() and load_references(reopened) == []


def test_reference_limits_and_missing_files_fail_explicitly(tmp_path):
    book = storage.create_book(tmp_path, "Style")
    invalid = tmp_path / "bad.png"
    invalid.write_text("not an image")
    with pytest.raises(PermanentError, match="readable"):
        add_reference(book, invalid)
    sample = tmp_path / "sample.png"
    sample.write_bytes(png_bytes(100, 100))
    for _ in range(3):
        add_reference(book, sample)
    with pytest.raises(PermanentError, match="up to 3"):
        add_reference(book, sample)
    (book.folder / load_references(book)[0]["file"]).unlink()
    with pytest.raises(PermanentError, match="missing"):
        reference_data_urls(book)


def test_references_cannot_read_outside_managed_folder(tmp_path):
    book = storage.create_book(tmp_path, "Style")
    manifest = book.folder / "style/references.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps([{"name": "outside", "file": "../outside.png"}]))
    with pytest.raises(PermanentError, match="Invalid"):
        reference_data_urls(book)


def test_llm_sends_reference_images_with_text_first(tmp_path):
    seen = []
    output = "data:image/png;base64," + base64.b64encode(png_bytes(20, 20)).decode()

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "", "images": [
            {"image_url": {"url": output}}]}}]})

    async def generate():
        client = OpenRouterClient("test", transport=httpx.MockTransport(handler))
        try:
            await client.generate_image("test/image", "New subject", aspect_ratio="2:3", size="2K",
                                        reference_images=[output, output])
        finally:
            await client.close()

    asyncio.run(generate())
    content = seen[0]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "New subject"}
    assert [p["image_url"]["url"] for p in content[1:]] == [output, output]
    assert seen[0]["image_config"] == {"aspect_ratio": "2:3", "image_size": "2K"}


def test_book_references_and_current_instructions_reach_each_generation_and_retry(tmp_path):
    session, curator, _ = make_session(tmp_path)
    sample = tmp_path / "sample.png"
    sample.write_bytes(png_bytes(100, 100))
    session.add_style_samples([sample])
    profile = session.profile
    profile.image_style = "Muted watercolour, soft light, no cartoon outlines"
    save_profile(session.book, profile)
    calls = []

    async def generate(model, prompt, **kwargs):
        calls.append((prompt, kwargs))
        if len(calls) == 1:
            raise TransientError("temporary failure")
        return LLMResult(text="", model=model, images=[png_bytes(30, 30)])

    curator.generate_image = generate
    slot = session.add_image_slot(1, "Scientific instrument", False)
    assert asyncio.run(session.generate_image(slot))
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert profile.image_style in calls[0][0]
    assert "visual style guide for this entire book" in calls[0][0]
    assert calls[0][1]["reference_images"] == reference_data_urls(session.book)
    session.remove_style_sample(load_references(session.book)[0]["file"])
    assert asyncio.run(session.generate_image(slot))
    assert "reference_images" not in calls[-1][1]


def test_cover_art_uses_same_book_references(tmp_path):
    from tests.test_cover import make_session as cover_session
    session, illuminator = cover_session(tmp_path)
    sample = tmp_path / "sample.png"
    sample.write_bytes(png_bytes(100, 100))
    session.add_style_samples([sample])
    profile = session.profile
    profile.image_style = "Soft warm watercolour"
    save_profile(session.book, profile)
    calls = []

    async def generate(model, prompt, **kwargs):
        calls.append((prompt, kwargs))
        return LLMResult(text="", model=model, images=[png_bytes(20, 30)])

    illuminator.generate_image = generate
    assert asyncio.run(session.make_cover_concepts())
    assert len(calls) == 3
    assert all(profile.image_style in prompt for prompt, _ in calls)
    assert all(options["reference_images"] == reference_data_urls(session.book) for _, options in calls)


def test_profile_shows_samples_and_roundtrips_shared_instructions(tmp_path):
    from bookguild.profile import BookProfile
    from bookguild.events import Status
    from bookguild.ui.profile_view import ProfileView

    view = ProfileView()
    view.set_profile(BookProfile(image_style="Watercolour\nMuted palette"), Status.WAITING)
    view.set_style_samples([{"name": "Sample", "file": "style/references/sample.png"}], tmp_path)
    assert view.current_profile().image_style == "Watercolour\nMuted palette"
    assert view.sample_list.count() == 1
    removed = []
    view.style_sample_removed.connect(removed.append)
    view.sample_list.setCurrentRow(0)
    view.remove_sample_button.click()
    assert removed == ["style/references/sample.png"]
    view.close()


def test_adding_samples_keeps_unsaved_profile_edits(tmp_path):
    from tests.test_main_window import make_window
    from bookguild.profile import BookProfile

    window = make_window(tmp_path)
    book = window.create_book("Style test")
    save_profile(book, BookProfile())
    window.open_book(book)
    view = window.profile_view
    view.widgets["image_style"].setPlainText("Keep these unsaved instructions")
    sample = tmp_path / "sample.png"
    sample.write_bytes(png_bytes(100, 100))
    view.style_samples_added.emit([sample])
    assert view.sample_list.count() == 1
    assert view.widgets["image_style"].toPlainText() == "Keep these unsaved instructions"
    assert view.save_button.isEnabled()
    window.close()
