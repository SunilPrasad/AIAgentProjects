"""Error types, retry policy and circuit breaker for every outside call (AI, search, images).

The rules that keep a broken call from burning tokens:
- Only TRANSIENT errors are retried (timeouts, rate limits, server errors, bad JSON),
  at most `max_retries` times with growing delays (2s, 4s, 8s).
- PERMANENT errors fail at once (bad key, no credits, model not found, refused).
- After 3 calls in a row have failed, the circuit breaker opens and the pipeline pauses
  until you press Resume.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable


class LLMError(Exception):
    """A failed outside call. `retryable` and `use_fallback` decide what happens next."""

    retryable = False

    def __init__(self, message: str, status: int | None = None, use_fallback: bool = True):
        super().__init__(message)
        self.message = message
        self.status = status
        self.use_fallback = use_fallback  # would a different model help?
        self.attempts = 0
        # The model's reply, when it answered but the answer was unusable (empty, cut off,
        # bad JSON). That attempt was still paid for, so the gateway charges its cost.
        self.result = None


class TransientError(LLMError):
    """Might work if we try again: timeout, rate limit, server error, unreadable reply."""

    retryable = True


class PermanentError(LLMError):
    """Will not fix itself by retrying."""


class BudgetExceeded(PermanentError):
    def __init__(self, spent_usd: float, limit_usd: float):
        super().__init__(f"Budget reached: ${spent_usd:.2f} of ${limit_usd:.2f} spent", use_fallback=False)


class PipelinePaused(PermanentError):
    def __init__(self):
        super().__init__("Pipeline is paused after repeated failures - press Resume to continue", use_fallback=False)


def classify_http_error(status: int, message: str) -> LLMError:
    """Turn an OpenRouter HTTP status into the right error type."""
    if status == 401:
        return PermanentError(f"Invalid OpenRouter API key ({message})", status, use_fallback=False)
    if status == 402:
        return PermanentError(f"Not enough OpenRouter credits ({message})", status, use_fallback=False)
    if status == 403:
        return PermanentError(f"Request refused by moderation ({message})", status)
    if status == 404:
        return PermanentError(f"Model not found ({message})", status)
    if status in (408, 429) or status >= 500:
        return TransientError(f"OpenRouter error {status}: {message}", status)
    return PermanentError(f"OpenRouter error {status}: {message}", status)


@dataclass
class RetryPolicy:
    max_retries: int = 3  # retries AFTER the first attempt
    base_delay_s: float = 2.0

    def delay_before_retry(self, retry_number: int) -> float:
        """retry 1 -> 2s, retry 2 -> 4s, retry 3 -> 8s."""
        return self.base_delay_s * (2 ** (retry_number - 1))


async def with_retries(call: Callable[[], Awaitable], policy: RetryPolicy,
                       sleep: Callable[[float], Awaitable],
                       on_retry: Callable[[LLMError, int, float], None] | None = None):
    """Run `call`, retrying transient errors by `policy`. Used for non-AI calls such as web
    searches (AI calls go through AIGateway, which also charges each attempt)."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return await call()
        except LLMError as error:
            error.attempts = attempt
            if not error.retryable or attempt - 1 >= policy.max_retries:
                raise
            delay = policy.delay_before_retry(attempt)
            if on_retry:
                on_retry(error, attempt, delay)
            await sleep(delay)


class CircuitBreaker:
    """Opens after `threshold` calls in a row have failed; stays open until reset()."""

    def __init__(self, threshold: int = 3):
        self.threshold = threshold
        self.consecutive_failures = 0

    @property
    def is_open(self) -> bool:
        return self.consecutive_failures >= self.threshold

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self) -> bool:
        """Record a failed call. Returns True if this failure just opened the breaker."""
        was_open = self.is_open
        self.consecutive_failures += 1
        return self.is_open and not was_open

    def reset(self) -> None:
        self.consecutive_failures = 0


_failure_ids = itertools.count(1)


@dataclass
class Failure:
    """One failed step, shown in the Failures panel."""

    stage: str
    agent: str
    model: str
    error: str
    kind: str  # "transient" or "permanent"
    attempts: int
    status: int | None = None
    id: int = field(default_factory=lambda: next(_failure_ids))
    time: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    retry: Callable[[], Awaitable] | None = field(default=None, repr=False)  # re-runs the same call
