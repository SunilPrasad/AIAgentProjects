import asyncio
import json

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage

from bookguild import storage
from bookguild.budget import Budget
from bookguild.chapters import ChapterRecord, save_records, write_file
from bookguild.events import EventBus, Status
from bookguild.gateway import AIGateway
from bookguild.images import SLOT_APPROVED, Candidate, credits_markdown, dpi_verdict, load_slots, print_dpi
from bookguild.llm import LLMResult
from bookguild.models import load_model_profiles
from bookguild.outline import ChapterPlan, Outline, save_outline
from bookguild.profile import BookProfile, save_profile
from bookguild.research.image_search import ImageHit, commons_hit, plain_text, reusable_licence
from bookguild.session import BookSession, quick_command

MODELS = load_model_profiles()["test"]


def png_bytes(width=2000, height=1200) -> bytes:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


# ---------- Commons licence rules ----------

def commons_page(licence="CC BY-SA 3.0", url="https://creativecommons.org/licenses/by-sa/3.0", artist="Jane Doe",
                 restrictions="", mime="image/jpeg", usage="", width=3000, height=2000):
    meta = {"LicenseShortName": {"value": licence}, "LicenseUrl": {"value": url}, "Artist": {"value": artist},
            "Restrictions": {"value": restrictions}, "UsageTerms": {"value": usage}}
    return {"title": "File:Homi Bhabha.jpg", "imageinfo": [{
        "mime": mime, "width": width, "height": height, "url": "https://upload.wikimedia.org/x/Homi.jpg",
        "thumburl": "https://upload.wikimedia.org/thumb/x/Homi.jpg/600px-Homi.jpg",
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Homi.jpg", "extmetadata": meta}]}


def test_commons_licence_rules():
    hit = commons_hit(commons_page())
    assert hit.license == "CC BY-SA 3.0" and hit.author == "Jane Doe"
    assert hit.full_url.endswith("/2400px-Homi.jpg") and hit.width == 2400  # print size, not the 3000px original

    public_domain = commons_hit(commons_page("Public domain", "", artist="Unknown", usage="Public domain"))
    assert public_domain.license == "Public domain" and public_domain.license_url.endswith("#Licensing")

    assert commons_hit(commons_page("CC BY-SA 2.0 de", "https://creativecommons.org/licenses/by-sa/2.0/de/deed.en"))
    assert commons_hit(commons_page("CC BY-NC 2.0", "https://creativecommons.org/licenses/by-nc/2.0")) is None
    assert commons_hit(commons_page(artist="")) is None  # creator must be named
    assert commons_hit(commons_page(restrictions="personality")) is None
    assert commons_hit(commons_page("GODL-India", "https://data.gov.in/x.pdf")) is None
    assert commons_hit(commons_page(mime="image/svg+xml")) is None


def test_licence_helpers():
    assert reusable_licence("CC0", "https://creativecommons.org/publicdomain/zero/1.0/")
    assert not reusable_licence("CC BY-ND 4.0", "https://creativecommons.org/licenses/by-nd/4.0")
    assert plain_text('<a href="//x">Konrad &amp; Co</a>') == "Konrad & Co"


def test_print_dpi():
    profile = BookProfile(trim_size="6x9")  # text width 4.75 in
    assert print_dpi(Candidate("c1", "ai", "t", "p", width=1408), profile) == 296
    assert dpi_verdict(296) == "ok if printed smaller than full width"
    assert dpi_verdict(1425 // 4.75) == "good for print"


def test_credits():
    from bookguild.images import ImageSlot

    slot = ImageSlot("ch01-1", 1, "Bhabha portrait", caption="Homi Bhabha", status=SLOT_APPROVED, chosen="c1",
                     candidates=[Candidate("c1", "commons", "Homi Bhabha 1960s", "p", author="Unknown",
                                           license="Public domain", license_url="https://x#Licensing",
                                           page_url="https://commons/x")])
    text = credits_markdown([slot])
    assert "Chapter 1, Homi Bhabha" in text and "Public domain" in text and "commons" in text


# ---------- the image stage, with fakes ----------

class FakeCurator:
    """Plans two images per chapter (one real subject, one idea) and paints AI images."""

    def __init__(self):
        self.images_painted = 0

    async def chat(self, model, messages, **kwargs):
        return LLMResult(text=json.dumps({"images": [
            {"purpose": "Homi Bhabha as a young man", "caption": "Homi Bhabha", "anchor": "born in 1909",
             "real_subject": True, "source": "ai", "search_query": "Homi Bhabha", "ai_prompt": "a man"},
            {"purpose": "A boy building a toy crane", "caption": "Building", "anchor": "Meccano sets",
             "real_subject": False, "source": "ai", "search_query": "toy crane", "ai_prompt": "a boy and a crane"},
        ]}), model=model, cost_usd=0.001)

    async def generate_image(self, model, prompt):
        self.images_painted += 1
        assert "no text" in prompt.lower() and "brand names" in prompt
        return LLMResult(text="", model=model, images=[png_bytes(1408, 768)], cost_usd=0.03)


class FakeImageSearch:
    def __init__(self):
        self.downloads = []

    def providers(self):
        return ["commons"]

    async def search(self, provider, query, limit=4):
        if query == "toy crane":
            return []  # nothing licensed for the idea slot → mixed books paint one
        return [ImageHit("commons", f"{query} photo {i}", f"https://c/{i}/600px-a.jpg", f"https://c/{i}/full.jpg",
                         f"https://commons/{i}", "Unknown", "Public domain", "https://commons/x#Licensing", 2400, 3000)
                for i in range(2)]

    async def download(self, url):
        self.downloads.append(url)
        return png_bytes(2400 if "full" in url else 600, 800)

    async def close(self):
        pass


def make_session(tmp_path, strategy="mixed"):
    book = storage.create_book(tmp_path, "Legends")
    save_profile(book, BookProfile(working_title="Legends", image_strategy=strategy, images_per_chapter=2,
                                   approved=True))
    save_outline(book, Outline("Legends", chapters=[ChapterPlan("Bhabha")], approved=True))
    save_records(book, [ChapterRecord(1, "Bhabha", status=Status.DONE)])
    write_file(book, 1, "final.md", "# Bhabha\n\nHomi was born in 1909 [S1]. He loved Meccano sets [S2].")
    bus = EventBus()
    curator, search = FakeCurator(), FakeImageSearch()

    async def no_sleep(_):
        pass

    def make_gateway(step_retry=None, cost_tag=""):
        return AIGateway(curator, bus, Budget.for_book(book), sleep=no_sleep, step_retry=step_retry)

    session = BookSession(book, bus, make_gateway, lambda: MODELS, make_image_search=lambda: search)
    return session, curator, search


def test_plan_finds_licensed_for_real_subjects_and_paints_ideas(tmp_path):
    session, curator, _ = make_session(tmp_path)
    assert asyncio.run(session.plan_images()) is True

    real, idea = load_slots(session.book)
    assert real.real_subject and real.source == "licensed"  # the Curator asked for AI; the code refused
    assert [c.provider for c in real.candidates] == ["commons", "commons"]
    assert (session.book.folder / real.candidates[0].preview).exists()
    assert [c.provider for c in idea.candidates] == ["ai"] and curator.images_painted == 1
    assert session.book.stages["images"] == Status.WAITING


def test_approve_skip_and_credits(tmp_path):
    session, _, search = make_session(tmp_path)
    asyncio.run(session.plan_images())
    asyncio.run(session.approve_image("ch01-1", "c2"))

    real = load_slots(session.book)[0]
    assert real.status == SLOT_APPROVED and real.chosen == "c2"
    assert (session.book.folder / real.file).exists() and "https://c/1/full.jpg" in search.downloads
    assert real.candidates[1].width == 2400

    session.skip_image("ch01-2")
    assert session.book.stages["images"] == Status.DONE
    credits = (session.book.folder / "images/credits.md").read_text(encoding="utf-8")
    assert "Homi Bhabha photo 1" in credits


def test_manual_ai_generation_is_available_for_real_subjects(tmp_path):
    session, curator, _ = make_session(tmp_path)
    asyncio.run(session.plan_images())
    assert asyncio.run(session.generate_image("ch01-1")) is True
    assert curator.images_painted == 2


def test_licensed_only_books_never_paint(tmp_path):
    session, curator, _ = make_session(tmp_path, strategy="licensed_web")
    asyncio.run(session.plan_images())
    assert curator.images_painted == 0
    assert all(s.source == "licensed" for s in load_slots(session.book))


def test_upload_is_approved_at_once(tmp_path):
    session, _, _ = make_session(tmp_path)
    asyncio.run(session.plan_images())
    mine = tmp_path / "my photo.png"
    mine.write_bytes(png_bytes(3000, 2000))

    assert "now used" in session.upload_image("ch01-1", mine)
    slot = load_slots(session.book)[0]
    chosen = slot.candidate(slot.chosen)
    assert chosen.provider == "upload" and chosen.license == "user-provided" and chosen.width == 3000
    assert (session.book.folder / slot.file).exists()

    not_image = tmp_path / "notes.png"
    not_image.write_text("hello")
    assert "not an image" in session.upload_image("ch01-1", not_image)


def test_add_slot_and_commands(tmp_path):
    session, _, _ = make_session(tmp_path)
    slot_id = session.add_image_slot(1, "The Tata Institute building", real_subject=True)
    assert slot_id == "ch01-1"
    assert session.book.stages["images"] == Status.WAITING
    assert quick_command("find images").action == "plan_images"
    assert quick_command("skip image ch01-1").args == {"slot_id": "ch01-1"}


def test_no_images_profile_is_refused(tmp_path):
    session, _, _ = make_session(tmp_path, strategy="none")
    replies = []
    session.bus.steward_replied.connect(replies.append)
    assert asyncio.run(session.plan_images()) is False
    assert "no images" in replies[-1]



def test_empty_search_retries_with_just_the_names(tmp_path):
    from bookguild.stages import images as images_stage

    class PickySearch(FakeImageSearch):
        def __init__(self):
            super().__init__()
            self.queries = []

        async def search(self, provider, query, limit=4):
            self.queries.append(query)
            return [] if "portrait" in query else await super().search(provider, query, limit)

    session, _, _ = make_session(tmp_path)
    search = PickySearch()
    job = images_stage.ImageJob(session.book, session.profile, session.outline, session.make_gateway(), MODELS,
                                search, session.bus)
    hits = asyncio.run(images_stage.search_with_shorter_query(job, "commons", "Homi Bhabha 1930s portrait"))
    assert search.queries == ["Homi Bhabha 1930s portrait", "Homi Bhabha"] and len(hits) == 2


def test_missing_search_query_falls_back_to_purpose(tmp_path):
    session, curator, _ = make_session(tmp_path)

    async def chat(model, messages, **kwargs):
        return LLMResult(text=json.dumps({"images": [{"purpose": "A generic 1920s street", "search_query": None,
                                                      "real_subject": False, "source": "ai"}]}), model=model)
    curator.chat = chat
    asyncio.run(session.plan_images())
    assert load_slots(session.book)[0].queries() == ["A generic 1920s street"]


def test_named_person_safety_net():
    from bookguild.stages.images import depicts_named_person

    chapter = "Raman was born in 1888. Raman loved music. Young Raman read books. Bhabha met Raman. Bhabha."
    assert depicts_named_person("A vintage-style illustration depicting young Chandru Raman as a child", chapter)
    assert not depicts_named_person("Depict the 'Bhabha scattering' interaction between an electron and a positron",
                                    chapter)
    assert not depicts_named_person("How light scatters in water", chapter)
    assert not depicts_named_person("A young man walking in a 1920s street", chapter)  # no named character


def test_ai_profile_generates_for_real_subjects_too(tmp_path):
    session, curator, _ = make_session(tmp_path, strategy="ai_generated")
    assert asyncio.run(session.plan_images())
    real, idea = load_slots(session.book)
    assert real.source == "ai" and real.candidates
    assert all(c.provider == "ai" for c in real.candidates)
    assert idea.source == "ai" and curator.images_painted == 2


def test_opener_uses_full_chapter_and_sections_are_optional(tmp_path):
    session, curator, _ = make_session(tmp_path)
    ending = "The chapter ends with an explanation of cosmic rays."
    write_file(session.book, 1, "final.md", "A chapter about science. " * 700 + ending)

    async def chat(model, messages, **kwargs):
        assert ending in messages[0]["content"]
        return LLMResult(text=json.dumps({"images": [
            {"purpose": "Cosmic ray diagram", "role": "chapter", "source": "ai",
             "search_queries": ["cosmic rays", "particle detector", "cloud chamber"]}
        ]}), model=model)

    curator.chat = chat
    assert asyncio.run(session.plan_images())
    slots = load_slots(session.book)
    assert len(slots) == 1 and slots[0].role == "chapter"


def test_all_search_phrases_are_pooled_and_custom_search_is_saved(tmp_path):
    from bookguild.images import ImageSlot, save_slots

    class BroadSearch(FakeImageSearch):
        def __init__(self):
            super().__init__()
            self.queries = []

        async def search(self, provider, query, limit=4):
            self.queries.append(query)
            return [ImageHit("commons", query, f"https://c/{query}/{i}.jpg", f"https://c/{query}/{i}/full.jpg",
                             "https://commons/example", "Author", "CC0", "https://license", 2400, 1600)
                    for i in range(3)]

    session, _, _ = make_session(tmp_path)
    search = BroadSearch()
    session.make_image_search = lambda: search
    phrases = ["Bhabha", "Tata Institute", "cosmic rays", "Cavendish Laboratory"]
    save_slots(session.book, [ImageSlot("ch01-1", 1, "Science", search_queries=phrases)])
    assert asyncio.run(session.find_more_images("ch01-1"))
    slot = load_slots(session.book)[0]
    assert search.queries == phrases
    assert len(slot.candidates) == 9
    assert set(c.found_by for c in slot.candidates) == set(phrases)
    assert asyncio.run(session.find_more_images("ch01-1", "cloud chamber"))
    assert search.queries[-1] == "cloud chamber"
    assert load_slots(session.book)[0].candidates[-1].found_by == "cloud chamber"
    assert asyncio.run(session.find_more_images("ch01-1", "cloud chamber"))
    assert len(load_slots(session.book)[0].candidates) == 12  # no duplicates


def test_legacy_manifest_still_loads(tmp_path):
    session, _, _ = make_session(tmp_path)
    path = session.book.folder / "images/manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"id": "ch01-1", "chapter": 1, "purpose": "Science",
                                 "search_query": "cosmic rays", "candidates": []}]))
    slot = load_slots(session.book)[0]
    assert slot.role == "section" and slot.queries() == ["cosmic rays"]


def test_reject_removes_preview_and_approved_copy(tmp_path):
    from bookguild.images import REJECTED, SLOT_NEEDS_CHOICE

    session, _, _ = make_session(tmp_path)
    asyncio.run(session.plan_images())
    asyncio.run(session.approve_image("ch01-1", "c1"))
    before = load_slots(session.book)[0]
    preview = session.book.folder / before.candidate("c1").preview
    approved = session.book.folder / before.file
    other = session.book.folder / before.candidate("c2").preview
    session.reject_image("ch01-1", "c1")
    slot = load_slots(session.book)[0]
    assert not preview.exists() and not approved.exists() and other.exists()
    assert slot.candidate("c1").status == REJECTED
    assert slot.status == SLOT_NEEDS_CHOICE and not slot.chosen and not slot.file
    session.reject_image("ch01-1", "c1")  # already removed is harmless


def test_reject_upload_preserves_original_and_reject_cannot_escape_book(tmp_path):
    from bookguild.images import save_slots

    session, _, _ = make_session(tmp_path)
    asyncio.run(session.plan_images())
    original = tmp_path / "original.png"
    original.write_bytes(png_bytes())
    session.upload_image("ch01-1", original)
    slot = load_slots(session.book)[0]
    copied = session.book.folder / slot.file
    session.reject_image(slot.id, slot.chosen)
    assert original.exists() and not copied.exists()
    slots = load_slots(session.book)
    slots[0].candidates[0].preview = str(original.resolve())
    save_slots(session.book, slots)
    session.reject_image(slots[0].id, slots[0].candidates[0].id)
    assert original.exists()


@pytest.mark.parametrize("strategy,real,search,paint", [
    ("ai_generated", False, False, True),
    ("ai_generated", True, False, True),
    ("licensed_web", False, True, True),
    ("mixed", False, True, True),
    ("mixed", True, True, True),
    ("none", False, False, True),
])
def test_image_buttons_follow_profile_and_hide_rejected(tmp_path, strategy, real, search, paint):
    from bookguild.images import ImageSlot, REJECTED
    from bookguild.ui.images_view import ImagesView, CandidateCard

    view = ImagesView()
    # A stale slot source must not override the current profile.
    slot = ImageSlot("ch01-1", 1, "Science", source="licensed", real_subject=real,
                     candidates=[Candidate("c1", "ai", "Rejected", "missing.png", status=REJECTED)])
    view.set_slots([slot], BookProfile(image_strategy=strategy), tmp_path, Status.WAITING)
    assert view.slot_buttons["find"].isEnabled() == search
    assert view.slot_buttons["own"].isEnabled() == search
    assert view.slot_buttons["ai"].isEnabled() == paint
    assert not view.cards_widget.findChildren(CandidateCard)
    if strategy == "ai_generated":
        assert view.table.item(0, 3).text() == "ai"
        assert "licensed images or your own only" not in view.slot_header.text()
    view.set_status(Status.RUNNING)
    view.show_slot()
    assert not any(view.slot_buttons[k].isEnabled() for k in ("find", "own", "ai"))
    view.set_status(Status.WAITING)
    assert view.slot_buttons["ai"].isEnabled() == paint
    view.close()


def test_session_actions_follow_profile(tmp_path):
    session, curator, _ = make_session(tmp_path, strategy="ai_generated")
    asyncio.run(session.plan_images())
    assert asyncio.run(session.find_more_images("ch01-2")) is False
    assert asyncio.run(session.generate_image("ch01-2")) is True
    profile = session.profile
    profile.image_strategy = "licensed_web"
    save_profile(session.book, profile)
    painted = curator.images_painted
    assert asyncio.run(session.generate_image("ch01-2")) is True
    assert curator.images_painted == painted + 1


def test_ai_profile_overrides_existing_real_licensed_slot(tmp_path):
    session, curator, _ = make_session(tmp_path, strategy="mixed")
    asyncio.run(session.plan_images())
    assert load_slots(session.book)[0].real_subject
    assert load_slots(session.book)[0].source == "licensed"
    profile = session.profile
    profile.image_strategy = "ai_generated"
    save_profile(session.book, profile)
    painted = curator.images_painted
    assert asyncio.run(session.find_more_images("ch01-1")) is False
    assert asyncio.run(session.generate_image("ch01-1")) is True
    assert curator.images_painted == painted + 1
    assert load_slots(session.book)[0].candidates[-1].provider == "ai"


@pytest.mark.parametrize("strategy", ["ai_generated", "licensed_web", "mixed", "none"])
def test_manual_generation_overrides_every_profile_for_real_subject(tmp_path, strategy):
    session, curator, _ = make_session(tmp_path, strategy=strategy)
    slot_id = session.add_image_slot(1, "SLV-3 rocket at Sriharikota", real_subject=True)
    assert asyncio.run(session.generate_image(slot_id)) is True
    assert curator.images_painted == 1
    assert load_slots(session.book)[0].candidates[-1].provider == "ai"


def test_generate_whole_chapter_image_preserves_legacy_section_slots(tmp_path):
    session, curator, _ = make_session(tmp_path)
    asyncio.run(session.plan_images())
    session.skip_image("ch01-2")
    before = load_slots(session.book)
    # Simulate the pre-opener manifests from existing books.
    from bookguild.images import save_slots
    for slot in before:
        slot.role = "section"
    save_slots(session.book, before)
    ending = "The chapter ends by connecting all these discoveries."
    write_file(session.book, 1, "final.md", "Science and discovery. " * 800 + ending)
    calls = []

    async def chat(model, messages, **kwargs):
        calls.append(messages[0]["content"])
        assert ending in messages[0]["content"]
        return LLMResult(text=json.dumps({"images": [{"role": "chapter", "purpose": "Discoveries together",
                           "real_subject": False, "source": "ai", "ai_prompt": "A scientific instrument"}]}),
                         model=model)

    curator.chat = chat
    assert asyncio.run(session.generate_chapter_image(1))
    slots = load_slots(session.book)
    opener = next(s for s in slots if s.role == "chapter")
    assert len(slots) == 3 and opener.id == "ch01-3"
    assert opener.candidates[0].provider == "ai"
    assert [s for s in slots if s.role == "section"] == before
    assert asyncio.run(session.generate_chapter_image(1))
    assert len(calls) == 1  # reuse the saved whole-chapter plan
    assert len(load_slots(session.book)[0].candidates) == 2


def test_chapter_image_requires_written_chapter_and_respects_busy(tmp_path):
    session, curator, _ = make_session(tmp_path)
    assert asyncio.run(session.generate_chapter_image(2)) is False
    session.busy = "another paid step"
    assert asyncio.run(session.generate_chapter_image(1)) is False
    assert curator.images_painted == 0


def test_chapter_image_button_emits_selected_chapter(tmp_path, monkeypatch):
    from bookguild.images import ImageSlot
    from bookguild.ui.images_view import ImagesView
    from PySide6.QtWidgets import QInputDialog

    view = ImagesView()
    view.set_slots([ImageSlot("ch03-1", 3, "Science")], BookProfile(), tmp_path, Status.WAITING)
    received = []
    view.chapter_image_requested.connect(received.append)

    def choose(*args):
        assert args[3] == 3
        return 3, True

    monkeypatch.setattr(QInputDialog, "getInt", choose)
    view.chapter_image_button.click()
    assert received == [3]
    view.set_status(Status.RUNNING)
    assert not view.chapter_image_button.isEnabled()
    view.close()
