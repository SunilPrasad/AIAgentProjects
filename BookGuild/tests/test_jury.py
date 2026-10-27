import asyncio
import json
import random

import pytest

from bookguild.budget import Budget
from bookguild.events import EventBus
from bookguild.gateway import AIGateway
from bookguild.jury import Ballot, Criterion, count_votes, judge, parse_ballot
from bookguild.llm import LLMResult
from bookguild.models import load_model_profiles
from bookguild.reliability import PermanentError, TransientError

RUBRIC = [Criterion("accuracy", "true", 3), Criterion("style", "nice", 1)]
MODELS = load_model_profiles()["test"]


class FakeCouncil:
    """Each juror prefers the candidate whose text contains 'BEST'. Jurors in `broken` refuse."""

    def __init__(self, broken=(), first_bad_ballot=False):
        self.broken, self.first_bad_ballot, self.calls = set(broken), first_bad_ballot, []

    async def chat(self, model, messages, **kwargs):
        prompt = messages[0]["content"]
        self.calls.append(model)
        if model == MODELS.chair:
            return LLMResult(text=json.dumps({"note": "- tighten chapter 2"}), model=model, cost_usd=0.001)
        if model in self.broken:
            raise PermanentError("refused", 403, use_fallback=False)
        if self.first_bad_ballot:
            self.first_bad_ballot = False
            return LLMResult(text=json.dumps({"scores": {}, "ranking": ["A"], "reasons": {}}), model=model)
        labels = [line.split("CANDIDATE ")[1].split(" ")[0] for line in prompt.splitlines()
                  if line.startswith("===== CANDIDATE")]
        texts = prompt.split("===== CANDIDATE ")[1:]
        best = next(label for label, text in zip(labels, texts) if "BEST" in text)
        ranking = [best] + [label for label in labels if label != best]
        scores = {label: {"accuracy": 9 if label == best else 4, "style": 6} for label in labels}
        return LLMResult(text=json.dumps({"scores": scores, "ranking": ranking,
                                          "reasons": {label: f"reason {label}" for label in labels}}),
                         model=model, cost_usd=0.001)


def make_gateway(client):
    async def no_sleep(_):
        pass

    return AIGateway(client, EventBus(), Budget(5.0), sleep=no_sleep)


def run_judge(client, candidates, seed=1):
    return asyncio.run(judge(make_gateway(client), MODELS, "outline", "task", "context", candidates, RUBRIC,
                             rng=random.Random(seed)))


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_winner_is_found_whatever_the_shuffle(seed):
    verdict = run_judge(FakeCouncil(), ["plain", "the BEST one", "meh"], seed)
    assert verdict.winner == 1
    assert verdict.points[1] == 2 * len(MODELS.jurors)  # first place on every ballot (n-1 = 2 points)
    assert verdict.chair_note == "- tighten chapter 2"
    assert all(b.reasons[1] for b in verdict.ballots)  # reasons are mapped back to the right candidate


def test_one_juror_failing_still_gives_a_verdict():
    verdict = run_judge(FakeCouncil(broken={MODELS.jurors[0]}), ["BEST", "other"])
    assert verdict.winner == 0
    assert verdict.failed_jurors == ["Juror-1"] and len(verdict.ballots) == len(MODELS.jurors) - 1


def test_too_few_ballots_is_a_failure():
    with pytest.raises(PermanentError, match="not enough"):
        run_judge(FakeCouncil(broken=set(MODELS.jurors[:2])), ["BEST", "other"])


def test_malformed_ballot_is_retried():
    client = FakeCouncil(first_bad_ballot=True)
    verdict = run_judge(client, ["BEST", "other"])
    assert verdict.winner == 0 and len(verdict.ballots) == len(MODELS.jurors)


def test_parse_ballot_checks_ranking_and_clamps_scores():
    ranking, scores, reasons = parse_ballot(
        {"ranking": ["b", "A"], "scores": {"A": {"accuracy": 14, "style": "x"}}, "reasons": {"A": "ok"}}, "AB", RUBRIC)
    assert ranking == ["B", "A"]
    assert scores["A"] == {"accuracy": 10, "style": 5} and scores["B"] == {"accuracy": 5, "style": 5}
    assert reasons == {"A": "ok", "B": ""}
    with pytest.raises(TransientError):
        parse_ballot({"ranking": ["A", "A"]}, "AB", RUBRIC)


def test_borda_count_and_tie_break_by_weighted_score():
    ballots = [Ballot("J1", "m", [0, 1], {0: {"accuracy": 9, "style": 1}, 1: {"accuracy": 5, "style": 9}}, {}),
               Ballot("J2", "m", [1, 0], {0: {"accuracy": 9, "style": 1}, 1: {"accuracy": 5, "style": 9}}, {})]
    points, weighted = count_votes(ballots, 2, RUBRIC)
    assert points == {0: 1, 1: 1}  # a tie on points...
    assert weighted[0] > weighted[1]  # ...broken by accuracy, which weighs 3x
