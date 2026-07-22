# Multi-Currency Total Profit Agent

A production-ready AI agent, built on the **Microsoft Agent Framework**
(`Microsoft.Agents.AI` + `Microsoft.Extensions.AI`), that totals profit values reported in
different currencies. It follows a strict Reason → Act → Observe loop: every non-target
currency is converted using a real, live exchange rate (never guessed), and the total is only
produced once every required conversion and the final calculation have succeeded.

## How it works

- **`ChatClientAgent`** (Microsoft Agent Framework) drives the Reason/Act/Observe loop natively —
  there is no hand-written orchestration loop.
- **`CurrencyConversionTool`** converts one amount between two ISO 4217 currencies using the free,
  keyless [Frankfurter API](https://frankfurter.dev) (ECB reference rates). Independent
  conversions the model requests in the same turn run in **parallel**
  (`FunctionInvokingChatClient.AllowConcurrentInvocation = true`).
- **`ProfitCalculationTool`** sums already-same-currency amounts with `decimal` precision and
  banker's rounding to 2 decimal places.
- The agent's final answer is constrained to the `TotalProfitReport` JSON schema
  (`ChatResponseFormat.ForJsonSchema`), so the output is always structured and parseable.
- Tool invocation and chat requests are logged via the framework's native
  `.UseFunctionInvocation(...)` / `.UseLogging(...)` middleware — no custom logging code.

## Project layout

```
src/CalculateTotalRevenue/
  Program.cs                 Host/DI wiring, logging, example runs
  appsettings.json            Non-secret defaults (model id, Frankfurter base URL)
  Configuration/               Options classes (AgentOptions, ExchangeRateOptions)
  Models/                      ExchangeRateQuote, CurrencyConversionResult, CalculationResult, TotalProfitReport
  Services/                     IExchangeRateProvider + FrankfurterExchangeRateProvider
  Tools/                        CurrencyConversionTool, ProfitCalculationTool
  Agents/                       AgentInstructions (ReAct system prompt), ProfitAgentFactory
```

## Setup

The agent calls an OpenAI model (`openai/gpt-4o-mini` by default) through
[OpenRouter](https://openrouter.ai)'s OpenAI-compatible endpoint. You need an OpenRouter API key:

```powershell
setx OPENROUTER_API_KEY "sk-or-..."
```

(Restart your shell/terminal after `setx` so the variable is picked up.)

No key is needed for currency conversion — the Frankfurter API is free and keyless.

## Run

```bash
cd src/CalculateTotalRevenue
dotnet run
```

This runs three example prompts:

1. A multi-currency total (USD + EUR + GBP → USD) — exercises parallel conversion.
2. A same-currency total (USD + USD) — no conversion tool call needed.
3. An invalid currency code — demonstrates the agent reporting a failure instead of a
   fabricated total.

Set `Microsoft.Extensions.AI` logging below `Debug` in `Program.cs` if you want quieter output;
it's set to `Debug` by default so you can see each tool call and its arguments/result.

## Configuration

Edit `appsettings.json` to change the model or exchange-rate provider base URL:

```json
{
  "Agent": { "Endpoint": "https://openrouter.ai/api/v1", "ModelId": "openai/gpt-4o-mini" },
  "ExchangeRate": { "BaseUrl": "https://api.frankfurter.dev", "TimeoutSeconds": 10 }
}
```
