# Great Indians — C# Microsoft Agent Framework prototype

**Goal:** inspiring, researched narrative biographies for ages 8–12; not short picture-storybooks. Text and artwork are independent production stages.

## Current implementation
- C#/.NET console application; Microsoft Agent Framework `AIAgent` writer, reviser, art director.
- Separate Claude API reviewer; fail-closed on invalid/missing reviewer results.
- Human-approved evidence input with references and exact excerpts required before writing.
- Up to three reviews; per-pass drafts and reviewer outputs retained on disk.
- Generates illustration *briefs*, not actual images. Human approval remains mandatory.

## Prerequisites
- .NET 10 SDK
- OpenAI API key (`OPENAI_API_KEY`)
- Anthropic API key (`ANTHROPIC_API_KEY`)
- Correct available model IDs configured in `WRITER_MODEL` and `REVIEWER_MODEL`.
- ChatGPT Plus does **not** include API credits.

## Run
```powershell
cd GreatIndians.Factory
$env:OPENAI_API_KEY="..."
$env:ANTHROPIC_API_KEY="..."
$env:WRITER_MODEL="gpt-4.1"
$env:REVIEWER_MODEL="claude-sonnet-4-5"
dotnet restore
dotnet run -- chapter ../examples/aryabhata.approved-evidence.example.json ../output/aryabhata
```
The supplied example is intentionally **unapproved** and has placeholder source evidence. It MUST fail until replaced with checked excerpts and `researchApprovedByHuman` is set to true after actual verification.

## Staged plan
1. Add web/source retrieval with citation offsets and source snapshot hashes; don't let an LLM certify its own sources.
2. Convert manual orchestration to MAF typed `Executor<TIn,TOut>` workflows with checkpoints/parallel reviewers; current MVP uses MAF agents coordinated in C# application logic.
3. Add independent visual generation with persistent character sheets, image API, image review, manual acceptance.
4. Add PDF/EPUB layout and KDP validation with printable proof review.
5. Add tests, run telemetry, retry/rate limiting, and review dashboard.

## Limitations and safeguards
- This code is a **starter**, not a proven production pipeline. It has not been compiled or API-tested in this environment because the .NET SDK is unavailable.
- A reviewer seeing the evidence ledger cannot independently verify source authenticity. Source retrieval and human checking are indispensable.
- Current JSON parsing rejects malformed output; model can still misunderstand facts. Human editorial review required.
- The model IDs and NuGet package versions can change; verify against official documentation.
- API keys must not be committed to source control.
