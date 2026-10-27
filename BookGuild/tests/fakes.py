"""Shared test doubles."""

from bookguild.llm import LLMResult


class ScriptedClient:
    """Fake OpenRouter client. `script` maps model -> list of outcomes (an exception or reply text)."""

    def __init__(self, script: dict[str, list]):
        self.script = {model: list(outcomes) for model, outcomes in script.items()}
        self.calls: list[str] = []

    async def chat(self, model, messages, **kwargs):
        self.calls.append(model)
        outcome = self.script[model].pop(0) if len(self.script[model]) > 1 else self.script[model][0]
        if isinstance(outcome, Exception):
            raise outcome
        return LLMResult(text=outcome, model=model, input_tokens=100, output_tokens=20, cost_usd=0.01)
