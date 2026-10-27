"""A small OpenRouter client. Each method makes exactly ONE HTTP request.

Retries, fallbacks, budget and logging are NOT done here - see gateway.py.
Every failure is raised as a TransientError or PermanentError (reliability.py).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

import httpx

from bookguild.reliability import PermanentError, TransientError, classify_http_error

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT_S = 180.0


@dataclass
class LLMResult:
    text: str
    model: str  # the model that actually answered
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    images: list[bytes] = field(default_factory=list)
    finish_reason: str = ""  # "stop" = finished normally, "length" = cut off at max_tokens
    data: object = None  # parsed JSON, filled in by gateway.chat_json


@dataclass
class ModelInfo:
    id: str
    name: str
    input_per_m: float  # USD per million input tokens
    output_per_m: float
    context_length: int
    output_modalities: list[str]

    @property
    def makes_images(self) -> bool:
        return "image" in self.output_modalities


class OpenRouterClient:
    def __init__(self, api_key: str | None, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        self.api_key = api_key
        self._transport, self._timeout_s = transport, timeout_s
        self._http: httpx.AsyncClient | None = None

    @property
    def http(self) -> httpx.AsyncClient:
        """Created on first use: setting up the secure connection takes about a second, which would
        otherwise slow every app start and every window."""
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=self._timeout_s, transport=self._transport)
        return self._http

    async def chat(self, model: str, messages: list[dict], *, max_tokens: int | None = None,
                   temperature: float | None = None, json_mode: bool = False,
                   thinking: str | None = None) -> LLMResult:
        """thinking: None = the model's default, "off" = no hidden reasoning (fast and cheap,
        best for planning/routing/JSON jobs), or "low" / "medium" / "high"."""
        payload: dict = {"model": model, "messages": messages, "usage": {"include": True}}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if thinking == "off":
            payload["reasoning"] = {"enabled": False}
        elif thinking:
            payload["reasoning"] = {"effort": thinking}

        data = await self._post("/chat/completions", payload)
        result = _parse_completion(data, model)
        if not result.text.strip():
            message = (cut_off_message(model, max_tokens) if result.finish_reason == "length"
                       else f"{model} returned an empty reply")
            error = TransientError(message)
            error.result = result
            raise error
        return result

    async def generate_image(self, model: str, prompt: str, aspect_ratio: str = "", size: str = "",
                             reference_images: list[str] | None = None) -> LLMResult:
        """aspect_ratio e.g. "2:3" (portrait cover); size e.g. "2K" (only some models support it)."""
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["image", "text"],
            "usage": {"include": True},
        }
        config = {k: v for k, v in (("aspect_ratio", aspect_ratio), ("image_size", size)) if v}
        if reference_images:
            payload["messages"][0]["content"] = [{"type": "text", "text": prompt}] + [
                {"type": "image_url", "image_url": {"url": url}} for url in reference_images
            ]
        if config:
            payload["image_config"] = config
        result = _parse_completion(await self._post("/chat/completions", payload), model)
        if not result.images:
            raise TransientError(f"{model} returned no image")
        return result

    async def list_models(self) -> list[ModelInfo]:
        data = await self._request("GET", "/models")
        models = []
        for m in data.get("data", []):
            pricing = m.get("pricing", {})
            try:
                input_per_m = float(pricing.get("prompt", 0)) * 1_000_000
                output_per_m = float(pricing.get("completion", 0)) * 1_000_000
            except (TypeError, ValueError):
                continue
            if input_per_m < 0 or output_per_m < 0:  # "auto" routers have no fixed price
                continue
            models.append(ModelInfo(
                id=m["id"],
                name=m.get("name", m["id"]),
                input_per_m=input_per_m,
                output_per_m=output_per_m,
                context_length=m.get("context_length") or 0,
                output_modalities=m.get("architecture", {}).get("output_modalities", ["text"]),
            ))
        return sorted(models, key=lambda m: m.id)

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def _post(self, path: str, payload: dict) -> dict:
        return await self._request("POST", path, json=payload)

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        if not self.api_key:
            raise PermanentError("OpenRouter API key not found - check your environment variable",
                                 use_fallback=False)
        headers = {"Authorization": f"Bearer {self.api_key}", "X-Title": "Book Guild"}
        try:
            response = await self.http.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException:
            raise TransientError("Request to OpenRouter timed out") from None
        except httpx.TransportError as error:
            raise TransientError(f"Network error: {error}") from None

        try:
            data = response.json()
        except ValueError:
            data = {}

        # OpenRouter reports some errors inside a 200 response body.
        error = data.get("error") if isinstance(data, dict) else None
        if response.status_code >= 400 or error:
            message = (error or {}).get("message") or response.text[:200] or "no details"
            code = (error or {}).get("code")
            status = response.status_code if response.status_code >= 400 else (code if isinstance(code, int) else 502)
            raise classify_http_error(status, message)
        if not isinstance(data, dict):
            raise TransientError("OpenRouter sent an unreadable response")
        return data


def cut_off_message(model: str, max_tokens: int | None) -> str:
    return (f"{model} was cut off at its {max_tokens}-token limit before finishing "
            "(often spent on hidden thinking)")


def _parse_completion(data: dict, requested_model: str) -> LLMResult:
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError):
        raise TransientError("OpenRouter response had no message") from None

    usage = data.get("usage") or {}
    return LLMResult(
        text=message.get("content") or "",
        finish_reason=choice.get("finish_reason") or "",
        model=data.get("model", requested_model),
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        cost_usd=float(usage.get("cost") or 0.0),
        images=[_decode_data_url(img["image_url"]["url"]) for img in message.get("images") or []
                if img.get("image_url", {}).get("url", "").startswith("data:")],
    )


def _decode_data_url(url: str) -> bytes:
    """'data:image/png;base64,....' -> raw bytes."""
    return base64.b64decode(url.split(",", 1)[1])
