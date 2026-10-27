"""The Council: a jury of AI models that picks the best of several candidates.

Used for outlines (Phase 5) and chapter drafts (Phase 6). How a vote works:

  1. Each juror gets every candidate, anonymised as A, B, C… in its OWN shuffled order
     (so position in the list can't bias the result), plus a scoring rubric.
  2. Each juror scores every candidate 1-10 on each rubric criterion, ranks them, and gives
     a one-line reason per candidate (strict JSON; a malformed ballot is retried).
  3. Rankings are combined with a Borda count: with n candidates, 1st place gets n-1 points,
     2nd gets n-2, … Ties are broken by the weighted rubric score.
  4. The Chair (a stronger model) reads the winner, the others and the jurors' reasons, and
     writes a short note on how to improve the winner - including what to borrow from the others.

Jurors run at the same time. If a juror fails, the vote goes on with the rest; at least
two ballots are needed (or all jurors, if fewer than two are configured).
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import asdict, dataclass, field

from bookguild import prompts
from bookguild.gateway import AIGateway
from bookguild.models import ModelProfile
from bookguild.reliability import LLMError, PermanentError, TransientError

LABELS = "ABCDEFGH"
JUROR_MAX_TOKENS = 6000


@dataclass
class Criterion:
    name: str  # short key used in the JSON, e.g. "accuracy"
    description: str
    weight: int = 1


@dataclass
class Ballot:
    juror: str
    model: str
    ranking: list[int]  # candidate indexes, best first
    scores: dict[int, dict[str, int]]  # candidate index -> criterion -> 1..10
    reasons: dict[int, str]


@dataclass
class Verdict:
    winner: int  # index into the candidates list
    points: dict[int, int]  # Borda points per candidate
    weighted: dict[int, float]  # average weighted rubric score per candidate
    ballots: list[Ballot]
    chair_note: str = ""
    failed_jurors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


async def judge(gateway: AIGateway, models: ModelProfile, stage: str, task: str, context: str,
                candidates: list[str], rubric: list[Criterion], rng: random.Random | None = None) -> Verdict:
    """Run the Council on `candidates` (plain-text renderings). Raises PermanentError if too few ballots."""
    rng = rng or random.Random()
    jurors = [f"Juror-{i + 1}" for i in range(len(models.jurors))]
    results = await asyncio.gather(
        *(cast_ballot(gateway, juror, models.jurors[i], models.fallback, stage, task, context, candidates, rubric,
                      rng) for i, juror in enumerate(jurors)),
        return_exceptions=True,
    )
    ballots = [r for r in results if isinstance(r, Ballot)]
    failed = [juror for juror, r in zip(jurors, results) if isinstance(r, LLMError)]
    for r in results:
        if isinstance(r, Exception) and not isinstance(r, LLMError):
            raise r  # a programming error - don't hide it

    if len(ballots) < min(2, len(jurors)):
        raise PermanentError(f"only {len(ballots)} of {len(jurors)} jurors voted - not enough for a fair verdict",
                             use_fallback=False)

    points, weighted = count_votes(ballots, len(candidates), rubric)
    winner = max(range(len(candidates)), key=lambda i: (points[i], weighted[i], -i))
    verdict = Verdict(winner=winner, points=points, weighted=weighted, ballots=ballots, failed_jurors=failed)
    verdict.chair_note = await chair_note(gateway, models, stage, task, context, candidates, verdict)
    return verdict


async def cast_ballot(gateway: AIGateway, juror: str, model: str, fallback: str, stage: str, task: str,
                      context: str, candidates: list[str], rubric: list[Criterion], rng: random.Random) -> Ballot:
    order = list(range(len(candidates)))
    rng.shuffle(order)  # order[k] = which candidate is shown with label LABELS[k]
    labels = LABELS[:len(candidates)]
    shown = "\n\n".join(f"===== CANDIDATE {labels[k]} =====\n{candidates[index]}" for k, index in enumerate(order))
    prompt = prompts.render("juror", task=task, context=context, rubric=rubric_text(rubric),
                            labels=", ".join(labels), candidates=shown,
                            example=json.dumps(example_ballot(labels, rubric)))

    def validate(data) -> None:
        parse_ballot(data, labels, rubric)  # raises TransientError on a malformed ballot, so it is retried

    result = await gateway.chat_json(
        agent=juror, stage=stage, model=model, fallback_model=fallback,
        messages=[{"role": "user", "content": prompt}], max_tokens=JUROR_MAX_TOKENS, thinking="low",
        required_keys=("scores", "ranking", "reasons"), validate=validate,
    )
    ranking, scores, reasons = parse_ballot(result.data, labels, rubric)
    to_index = {labels[k]: index for k, index in enumerate(order)}
    return Ballot(juror=juror, model=result.model,
                  ranking=[to_index[label] for label in ranking],
                  scores={to_index[label]: s for label, s in scores.items()},
                  reasons={to_index[label]: r for label, r in reasons.items()})


def parse_ballot(data: dict, labels: str, rubric: list[Criterion]):
    """Check a juror's JSON. Returns (ranking labels, scores by label, reasons by label)."""
    ranking = [str(label).strip().upper() for label in data.get("ranking") or []]
    if sorted(ranking) != sorted(labels):
        raise TransientError(f"Juror ranking {ranking} must list each of {', '.join(labels)} exactly once")
    raw_scores = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    raw_reasons = data.get("reasons") if isinstance(data.get("reasons"), dict) else {}
    scores = {}
    for label in labels:
        given = raw_scores.get(label) if isinstance(raw_scores.get(label), dict) else {}
        scores[label] = {c.name: _score(given.get(c.name)) for c in rubric}
    reasons = {label: str(raw_reasons.get(label, "")).strip() for label in labels}
    return ranking, scores, reasons


def count_votes(ballots: list[Ballot], n: int, rubric: list[Criterion]) -> tuple[dict[int, int], dict[int, float]]:
    """Borda points and average weighted rubric score (out of 10) per candidate."""
    points = {i: 0 for i in range(n)}
    totals = {i: 0.0 for i in range(n)}
    total_weight = sum(c.weight for c in rubric) or 1
    for ballot in ballots:
        for place, index in enumerate(ballot.ranking):
            points[index] += n - 1 - place
        for index, scores in ballot.scores.items():
            totals[index] += sum(c.weight * scores[c.name] for c in rubric) / total_weight
    weighted = {i: round(totals[i] / max(1, len(ballots)), 2) for i in range(n)}
    return points, weighted


async def chair_note(gateway: AIGateway, models: ModelProfile, stage: str, task: str, context: str,
                     candidates: list[str], verdict: Verdict) -> str:
    """The Chair's advice for improving the winner. A failed Chair doesn't cancel the verdict."""
    reasons = "\n".join(
        f"- {ballot.juror} on candidate {i + 1}: {ballot.reasons.get(i, '')}"
        for ballot in verdict.ballots for i in range(len(candidates)))
    others = "\n\n".join(f"===== OTHER CANDIDATE {i + 1} =====\n{c}"
                         for i, c in enumerate(candidates) if i != verdict.winner)
    prompt = prompts.render("chair", task=task, context=context, winner=candidates[verdict.winner],
                            others=others or "(none)", reasons=reasons)
    try:
        result = await gateway.chat_json(
            agent="Chair", stage=stage, model=models.chair, fallback_model=models.fallback,
            messages=[{"role": "user", "content": prompt}], max_tokens=3000, thinking="off",
            required_keys=("note",),
        )
    except LLMError:
        return ""
    return str(result.data.get("note", "")).strip()


def rubric_text(rubric: list[Criterion]) -> str:
    return "\n".join(f"- `{c.name}` (weight {c.weight}): {c.description}" for c in rubric)


def example_ballot(labels: str, rubric: list[Criterion]) -> dict:
    return {"scores": {label: {c.name: 7 for c in rubric} for label in labels},
            "ranking": list(labels),
            "reasons": {label: "one sentence" for label in labels}}


def _score(value) -> int:
    try:
        return max(1, min(10, int(round(float(value)))))
    except (TypeError, ValueError):
        return 5
