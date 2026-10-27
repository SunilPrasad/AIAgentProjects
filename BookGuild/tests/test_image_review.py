import asyncio
import json

import pytest

from bookguild.images import SLOT_APPROVED, load_slots
from bookguild.image_review import validate_review
from bookguild.llm import LLMResult
from bookguild.reliability import PermanentError, TransientError
from tests.test_images import make_session


def scripted_review(client, outcomes):
    original = client.chat
    calls = []

    async def chat(model, messages, **kwargs):
        if not isinstance(messages[0]["content"], list):
            return await original(model, messages, **kwargs)
        calls.append(messages)
        outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return LLMResult(text=json.dumps({"score": outcome, "feedback": f"Improve contrast, score {outcome}"}),
                         model=model)

    client.chat = chat
    return calls


@pytest.mark.parametrize("scores,attempts,accepted", [([71], 1, True), ([70, 71], 2, True),
                                                     ([30, 50, 70, 60], 4, False)])
def test_score_cutoff_refinement_limit_and_acceptance(tmp_path, scores, attempts, accepted):
    session, curator, _ = make_session(tmp_path)
    calls = scripted_review(curator, scores)
    slot_id = session.add_image_slot(1, "Scientific instrument", False)
    assert asyncio.run(session.generate_image(slot_id))
    slot = load_slots(session.book)[0]
    assert curator.images_painted == attempts
    assert len(slot.candidates) == attempts
    assert (slot.status == SLOT_APPROVED) == accepted
    assert [c.review_score for c in slot.candidates] == scores
    assert all(c.review_feedback and c.review_model for c in slot.candidates)
    assert [c.review_iteration for c in slot.candidates] == list(range(1, attempts + 1))
    assert len(calls[0][0]["content"]) == 2  # text plus actual image pixels
    if attempts > 1:
        assert "Improve contrast, score" in slot.candidates[1].prompt
    if not accepted:
        assert not slot.chosen
        assert asyncio.run(session.approve_image(slot_id, slot.candidates[-1].id)) is False


@pytest.mark.parametrize("score", [-1, 101, True, 70.5, "80", None])
def test_invalid_scores_are_rejected(score):
    with pytest.raises(TransientError):
        validate_review({"score": score, "feedback": "Reason"})


def test_reviewer_failure_preserves_image_without_accepting_or_repainting(tmp_path):
    session, curator, _ = make_session(tmp_path)
    scripted_review(curator, [PermanentError("vision model unavailable", use_fallback=False)])
    slot_id = session.add_image_slot(1, "Scientific instrument", False)
    assert asyncio.run(session.generate_image(slot_id)) is False
    slot = load_slots(session.book)[0]
    assert curator.images_painted == 1
    assert slot.candidates[0].review_state == "error"
    assert "unavailable" in slot.candidates[0].review_feedback
    assert (session.book.folder / slot.candidates[0].preview).exists()
    assert not slot.chosen
    scripted_review(curator, [90])
    assert asyncio.run(session.generate_image(slot_id))
    assert curator.images_painted == 1  # review retry uses the already saved pixels
    assert load_slots(session.book)[0].status == SLOT_APPROVED


def test_budget_stop_during_refinement_keeps_reviewed_image(tmp_path):
    session, curator, _ = make_session(tmp_path)
    session.book.budget_usd = 0.01
    scripted_review(curator, [40])
    slot_id = session.add_image_slot(1, "Scientific instrument", False)
    assert asyncio.run(session.generate_image(slot_id)) is False
    assert curator.images_painted == 1  # the first image exhausted budget; review cannot start
    assert load_slots(session.book)[0].candidates[0].review_state == "error"


def test_failed_cover_images_are_not_selected(tmp_path):
    from tests.test_cover import make_session as make_cover_session
    from bookguild.cover import load_cover

    session, illuminator = make_cover_session(tmp_path)
    scripted_review(illuminator, [70])
    assert asyncio.run(session.make_cover_concepts())
    spec = load_cover(session.book)
    assert len(illuminator.painted) == 12
    assert all(len(c.reviews) == 4 for c in spec.concepts)
    assert not spec.chosen and not spec.front_art
    assert "not passed" in session.choose_cover_concept("A")
