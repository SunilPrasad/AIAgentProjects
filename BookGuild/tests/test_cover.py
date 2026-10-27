import asyncio
import json

import pytest
from PySide6.QtGui import QImage

from bookguild import storage
from bookguild.budget import Budget
from bookguild.chapters import ChapterRecord, save_records, write_file
from bookguild.cover import CoverSpec, estimate_pages, load_cover, render_wrap, spine_width_in, wrap_size_in
from bookguild.events import EventBus, Status
from bookguild.gateway import AIGateway
from bookguild.llm import LLMResult
from bookguild.models import load_model_profiles
from bookguild.outline import ChapterPlan, Outline, save_outline
from bookguild.profile import BookProfile, save_profile
from bookguild.session import BookSession, quick_command
from bookguild.stages.cover import concept_from
from tests.test_images import png_bytes

MODELS = load_model_profiles()["test"]


def test_kdp_geometry():
    profile = BookProfile(trim_size="6x9", paper="white")
    assert spine_width_in(100, "white") == pytest.approx(0.2252)
    assert spine_width_in(100, "cream") == pytest.approx(0.25)
    width, height = wrap_size_in(profile, 100)
    assert width == pytest.approx(0.125 + 6 + 0.2252 + 6 + 0.125)
    assert height == pytest.approx(9.25)


def test_page_estimate(tmp_path):
    book = storage.create_book(tmp_path, "Tea")
    profile = BookProfile(words_per_page=250, target_pages=80)
    assert estimate_pages(book, profile, chapters=0) == 86  # target 80 + 6 front matter
    write_file(book, 1, "final.md", "word " * 5000)  # 20 pages of text
    assert estimate_pages(book, profile, chapters=1) == 26  # 20 + 6, even
    write_file(book, 1, "final.md", "word " * 100)
    assert estimate_pages(book, profile, chapters=1) == 24  # KDP minimum


def test_concept_colours_are_validated():
    concept = concept_from({"name": "Light", "background": "navy", "text_color": "#FFFFFF",
                            "title_position": "sideways"}, "A")
    assert concept.background == "#1f2a44" and concept.text_color == "#FFFFFF" and concept.title_position == "top"


class FakeIlluminator:
    def __init__(self):
        self.painted = []

    async def chat(self, model, messages, **kwargs):
        return LLMResult(text=json.dumps({"blurb": "Meet the scientists who changed the world.", "concepts": [
            {"name": f"Idea {i}", "art_prompt": f"art {i}", "title_position": "bottom" if i == 2 else "top",
             "background": "#102030", "text_color": "#ffffff", "accent": "#ffcc00"} for i in range(1, 4)]}),
            model=model)

    async def generate_image(self, model, prompt, aspect_ratio="", size=""):
        self.painted.append((model, aspect_ratio, size))
        assert "no text" in prompt.lower()
        return LLMResult(text="", model=model, images=[png_bytes(1696, 2528)], cost_usd=0.1)


def make_session(tmp_path):
    book = storage.create_book(tmp_path, "Legends")
    save_profile(book, BookProfile(working_title="Legends", trim_size="6x9", words_per_page=250, approved=True))
    save_outline(book, Outline("Legends of Modern Indian Science", "Adventures in curiosity",
                               chapters=[ChapterPlan("Bhabha")], approved=True))
    save_records(book, [ChapterRecord(1, "Bhabha", status=Status.DONE)])
    write_file(book, 1, "final.md", "word " * 25000)  # 100 pages of text
    bus = EventBus()
    illuminator = FakeIlluminator()

    def make_gateway(step_retry=None, cost_tag=""):
        return AIGateway(illuminator, bus, Budget.for_book(book), step_retry=step_retry)

    session = BookSession(book, bus, make_gateway, lambda: MODELS)
    return session, illuminator


def test_concepts_choose_author_and_approve(tmp_path):
    session, illuminator = make_session(tmp_path)
    assert asyncio.run(session.make_cover_concepts()) is True

    spec = load_cover(session.book)
    assert [c.id for c in spec.concepts] == ["A", "B", "C"]
    assert all(call == (MODELS.cover_image, "2:3", "2K") for call in illuminator.painted)
    assert spec.chosen == "A" and spec.front_art == "cover/concepts/A.png"
    assert spec.title == "Legends of Modern Indian Science" and spec.blurb.startswith("Meet")
    assert session.book.stages["cover"] == Status.WAITING

    session.choose_cover_concept("B")
    assert load_cover(session.book).title_position == "bottom"
    assert "needs a author" in session.approve_cover()

    assert quick_command("author is Sunil Bhardwaj").args == {"name": "Sunil Bhardwaj"}
    session.set_author("Jane Doe")
    assert "Cover approved" in session.approve_cover()
    assert session.book.stages["cover"] == Status.DONE

    pages = session.cover_pages()
    assert pages == 106  # 100 text pages + 6 front matter
    wrap = QImage(str(session.book.folder / "cover/wrap.png"))
    width, height = wrap_size_in(session.profile, pages)
    assert (wrap.width(), wrap.height()) == (round(width * 300), round(height * 300))
    assert (session.book.folder / "cover/wrap.pdf").read_bytes().startswith(b"%PDF")
    assert QImage(str(session.book.folder / "cover/ebook.jpg")).height() == 2560


def test_uploaded_front_art_skips_painting(tmp_path):
    session, illuminator = make_session(tmp_path)
    art = tmp_path / "my cover.png"
    art.write_bytes(png_bytes(1900, 2850))
    message = session.upload_cover_art("front", art)
    assert "310 dpi" in message and "good for print" in message

    asyncio.run(session.make_cover_concepts())
    assert illuminator.painted == []
    assert load_cover(session.book).front_art == "cover/front-art.png"


def test_preview_scale_draws_the_same_design(tmp_path):
    session, _ = make_session(tmp_path)
    spec = CoverSpec(title="Legends", author="Jane Doe", blurb="Text")
    full = render_wrap(session.book, spec, session.profile, 100)
    small = render_wrap(session.book, spec, session.profile, 100, scale=0.35)
    assert small.width() == round(full.width() * 0.35)
