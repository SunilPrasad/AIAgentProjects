"""The AI Gateway: the single door every AI call goes through.

For each call it:
  1. refuses to start if the pipeline is paused or the budget is spent
  2. marks the agent as working on the Guild Board
  3. calls OpenRouter, retrying transient errors (max 3 retries: 2s, 4s, 8s)
  4. if the model keeps failing, tries the fallback model once
  5. on success: adds the cost to the budget, writes costs.jsonl, marks the agent done
  6. on failure: marks the agent FAILED, reports a Failure (with a Retry action) and raises

    result = await gateway.chat(agent="Scout-1", stage="research", model=..., messages=[...])
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Awaitable, Callable

from bookguild import storage
from bookguild.budget import Budget
from bookguild.events import EventBus, Status
from bookguild.llm import LLMResult, OpenRouterClient, cut_off_message
from bookguild.reliability import (
    BudgetExceeded,
    CircuitBreaker,
    Failure,
    LLMError,
    PipelinePaused,
    RetryPolicy,
    TransientError,
)

Call = Callable[[str], Awaitable[LLMResult]]  # takes a model id, makes one request


class AIGateway:
    def __init__(self, client: OpenRouterClient, bus: EventBus, budget: Budget,
                 breaker: CircuitBreaker | None = None, policy: RetryPolicy | None = None,
                 sleep: Callable[[float], Awaitable] = asyncio.sleep,
                 step_retry: Callable[[], Awaitable] | None = None, cost_tag: str = ""):
        self.client = client
        self.bus = bus
        self.budget = budget
        self.breaker = breaker or CircuitBreaker()
        self.policy = policy or RetryPolicy()
        self.sleep = sleep  # replaced in tests so they don't wait
        # When set, the Failures panel's Retry re-runs this whole pipeline step
        # (e.g. "generate the profile") instead of only repeating the single AI call.
        self.step_retry = step_retry
        # Written into costs.jsonl as "item" (e.g. "ch03"), so per-chapter costs add up correctly
        # even when two chapters are being written at the same time.
        self.cost_tag = cost_tag

    async def chat(self, *, agent: str, stage: str, model: str, messages: list[dict],
                   fallback_model: str | None = None, max_tokens: int | None = None,
                   temperature: float | None = None, thinking: str | None = None,
                   validate: Callable[[str], None] | None = None) -> LLMResult:
        """thinking: None (model default), "off", "low", "medium" or "high" - see OpenRouterClient.chat.
        `validate(text)` may raise TransientError (e.g. "too short"); that attempt is retried and still charged."""
        async def call(m: str) -> LLMResult:
            result = await self.client.chat(m, messages, max_tokens=max_tokens, temperature=temperature,
                                            thinking=thinking)
            if validate is not None:
                try:
                    validate(result.text)
                except TransientError as error:
                    if result.finish_reason == "length":
                        error.message = cut_off_message(m, max_tokens)
                    error.result = result
                    raise
            return result

        async def retry() -> LLMResult:
            return await self.chat(agent=agent, stage=stage, model=model, messages=messages,
                                   fallback_model=fallback_model, max_tokens=max_tokens, temperature=temperature,
                                   thinking=thinking, validate=validate)

        return await self._run(agent, stage, model, fallback_model, call, retry)

    async def chat_json(self, *, agent: str, stage: str, model: str, messages: list[dict],
                        fallback_model: str | None = None, max_tokens: int | None = None,
                        thinking: str | None = None, required_keys: tuple[str, ...] = (),
                        validate: Callable[[object], None] | None = None) -> LLMResult:
        """Like chat(), but the reply must be a JSON object containing `required_keys`.
        It is parsed into result.data. `validate(data)` may raise TransientError for deeper checks.

        An unreadable, incomplete, invalid or cut-off reply counts as a transient error, so it is
        retried (and the wasted attempt is still charged to the budget).
        """
        async def call(m: str) -> LLMResult:
            result = await self.client.chat(m, messages, max_tokens=max_tokens, json_mode=True, thinking=thinking)
            try:
                result.data = parse_json_reply(result.text, required_keys)
                if validate is not None:
                    validate(result.data)
            except TransientError as error:
                if result.finish_reason == "length":
                    error.message = cut_off_message(m, max_tokens)
                error.result = result
                raise
            return result

        async def retry() -> LLMResult:
            return await self.chat_json(agent=agent, stage=stage, model=model, messages=messages,
                                        fallback_model=fallback_model, max_tokens=max_tokens,
                                        thinking=thinking, required_keys=required_keys, validate=validate)

        return await self._run(agent, stage, model, fallback_model, call, retry)

    async def generate_image(self, *, agent: str, stage: str, model: str, prompt: str, aspect_ratio: str = "",
                             size: str = "") -> LLMResult:
        async def call(m: str) -> LLMResult:
            if aspect_ratio or size:
                return await self.client.generate_image(m, prompt, aspect_ratio=aspect_ratio, size=size)
            return await self.client.generate_image(m, prompt)

        async def retry() -> LLMResult:
            return await self.generate_image(agent=agent, stage=stage, model=model, prompt=prompt,
                                             aspect_ratio=aspect_ratio, size=size)

        return await self._run(agent, stage, model, None, call, retry)

    # ---------- the shared logic ----------

    async def _run(self, agent: str, stage: str, model: str, fallback_model: str | None,
                   call: Call, retry: Callable[[], Awaitable]) -> LLMResult:
        try:
            if self.breaker.is_open:
                raise PipelinePaused()
            self.budget.check()
        except LLMError as error:
            self._report_failure(agent, stage, model, error, retry)
            raise

        self.bus.set_agent_status(agent, Status.RUNNING, model, stage)
        models = [model] + ([fallback_model] if fallback_model and fallback_model != model else [])
        attempts = 0

        for i, current_model in enumerate(models):
            if i > 0:
                self.bus.log(f"{models[i - 1]} failed ({last_error.message}) - switching to fallback model "
                             f"{current_model}", "warning", stage, agent)
            try:
                result = await self._call_with_retries(agent, stage, current_model, call)
            except LLMError as error:
                attempts += error.attempts
                last_error = error
                if not error.use_fallback:
                    break
                continue
            self._record_success(agent, stage, result)
            return result

        last_error.attempts = attempts
        self._report_failure(agent, stage, model, last_error, retry)
        raise last_error

    async def _call_with_retries(self, agent: str, stage: str, model: str, call: Call) -> LLMResult:
        attempt = 0
        while True:
            attempt += 1
            try:
                return await call(model)
            except LLMError as error:
                error.attempts = attempt
                if error.result is not None:  # the model answered badly - that attempt still cost money
                    self._charge(agent, stage, error.result, ok=False)
                    if error.result.finish_reason == "length":
                        # Cut off at max_tokens: the same request would be cut off again, so don't
                        # pay for identical retries - go straight to the fallback model (if any).
                        error.retryable = False
                retries_used = attempt - 1
                if not error.retryable or retries_used >= self.policy.max_retries:
                    raise
                delay = self.policy.delay_before_retry(retries_used + 1)
                self.bus.log(f"{error.message} - retry {retries_used + 1} of {self.policy.max_retries} "
                             f"in {delay:.0f}s", "warning", stage, agent)
                self.bus.set_agent_status(agent, Status.RUNNING,
                                          f"retry {retries_used + 1}/{self.policy.max_retries}", stage)
                await self.sleep(delay)

    def _record_success(self, agent: str, stage: str, result: LLMResult) -> None:
        self.breaker.record_success()
        self._charge(agent, stage, result, ok=True)
        tokens = result.input_tokens + result.output_tokens
        self.bus.set_agent_status(agent, Status.DONE, f"{tokens:,} tok · ${result.cost_usd:.4f}", stage)

    def _charge(self, agent: str, stage: str, result: LLMResult, ok: bool) -> None:
        """Add one paid attempt to the budget and costs.jsonl (failed attempts are paid for too)."""
        self.budget.add(result.cost_usd)
        self.bus.set_cost(self.budget.spent_usd, self.budget.limit_usd)
        if self.budget.book is not None:
            storage.append_cost(self.budget.book, {
                "stage": stage, "agent": agent, "model": result.model,
                "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                "cost_usd": result.cost_usd, "ok": ok, **({"item": self.cost_tag} if self.cost_tag else {}),
            })
        outcome = "" if ok else " (unusable reply, still paid)"
        self.bus.log(f"{result.model}: {result.input_tokens:,} in + {result.output_tokens:,} out tokens, "
                     f"${result.cost_usd:.6f}{outcome}", "debug", stage, agent)

    def _report_failure(self, agent: str, stage: str, model: str, error: LLMError, retry) -> None:
        kind = "transient" if error.retryable else "permanent"
        attempts_text = f" after {error.attempts} attempt(s)" if error.attempts else ""
        self.bus.set_agent_status(agent, Status.FAILED, error.message[:60], stage)
        self.bus.log(f"FAILED{attempts_text}: {error.message} [model={model}, status={error.status}]",
                     "error", stage, agent)
        self.bus.failure_added.emit(Failure(stage=stage, agent=agent, model=model, error=error.message,
                                            kind=kind, attempts=error.attempts, status=error.status,
                                            retry=self.step_retry or retry))
        if isinstance(error, (PipelinePaused, BudgetExceeded)):
            return  # deliberate stops, not signs of an outage
        if self.breaker.record_failure():
            reason = f"{self.breaker.threshold} calls failed in a row (last: {error.message})"
            self.bus.log(f"Pipeline paused: {reason}", "error", stage, "Steward")
            self.bus.pipeline_paused.emit(reason)


def parse_json_reply(text: str, required_keys: tuple[str, ...] = ()) -> object:
    """Parse a model's JSON reply, tolerating ```json fences.

    Raises TransientError if it is unreadable, or if `required_keys` are given and the
    reply is not an object containing all of them (e.g. a lazy "{}").
    """
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        data = json.loads(cleaned)
    except ValueError:
        raise TransientError("Model reply was not valid JSON") from None
    if required_keys:
        missing = [key for key in required_keys if not isinstance(data, dict) or key not in data]
        if missing:
            raise TransientError(f"Model reply was missing: {', '.join(missing)}")
    return data
