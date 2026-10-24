# Great Indians — automatic chapter writing

.NET 10 console application using real Microsoft Agent Framework agents and workflow executors,
OpenRouter, durable stage caches and local framework checkpoints. The product is an engaging,
evidence-backed chapter for readers aged 8–12. Generation completion and editorial approval are
recorded separately: an unresolved review no longer hides a chapter that has already been written.

## Read an example now

[**Aryabhata and the Sky That Would Not Stand Still**](examples/aryabhata.chapter.md) is a
776-word editorial example created from the retained source evidence. It demonstrates the revised
curiosity-led writing approach. It is not presented as an automatic pipeline run or an independently
approved chapter. [Editorial/source notes](examples/aryabhata.chapter-notes.md) accompany it.

## Run

From `GreatIndians/GreatIndians.Factory`:

```powershell
$env:OPENROUTER_API_KEY = "your OpenRouter API key"
dotnet run
```

The application loads `book.json` and `style-bible.md` automatically. The supplied book has 12
personalities; reduce the list to one for the first live run. An optional configuration path is
supported: `dotnet run -- C:\path\book.json`. Style and output paths are relative to that file.
Running from the project folder uses its source configuration, with the built copy as a fallback.
Keys belong in environment variables, not source control. No Azure or direct provider keys are needed.

OpenRouter model defaults:

- `writerModel`: `openai/gpt-4.1` — evidence selection, planning, writing, revision and narrative review
- `researchModel`: `openai/gpt-4.1` — web research
- `reviewerModel`: `anthropic/claude-sonnet-4.5` — historical, cultural and book-wide review

Model IDs include the author prefix. Ledger/review models must support JSON-schema outputs;
OpenRouter routing requires the response-format parameter instead of silently ignoring it.
Research uses `openrouter:web_search` with the Exa engine and bounded searches, billed through
OpenRouter. A separate Exa key is not required. Source candidates come from structured citations,
not URLs invented in prose. See [OpenRouter Chat Completions](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion)
and [web search](https://openrouter.ai/docs/guides/features/server-tools/web-search). Tool APIs can change;
the user performs live provider verification with their own credits.

## Where the chapter is saved

The obvious reading location is:

```text
GreatIndians/output/
  index.md
  chapters/
    01-aryabhata.md
    01-aryabhata-review.md
    01-aryabhata.status.json
    02-brahmagupta.md
    ...
```

The chapter file contains clean reading text. Its report carries findings, reviewer availability,
word count, selected pass, provenance and human approval status. Files appear as soon as a first
draft exists and are updated to the selected chapter after review. The console prints their paths.
The detailed book/run archive also contains `final.md` after chapter generation finishes, even when
review findings remain. Here **final means the selected output of this bounded generation run**;
it does not mean approved for publication. `IsFinalGenerated` and `PublicationApproved` are separate
status fields; publication approval stays false.

To recover existing drafts without any model calls or an API key:

```powershell
dotnet run -- --export-existing
```

This selects a reviewed candidate from saved run artifacts and exports it with its outstanding
findings. It never transfers old approval or changes the original archived review records. Exporting
updates the reading copy, so keep any manual edits separately before exporting or generating again.

## Approach and prompts

All role prompts are centralised and versioned in `PromptSet.cs`. The permanent Style Bible is a
separate editable document. The framework adapter forwards agent instructions as system messages.

1. Search and retrieve sources. Save URLs, text snapshots, timestamps and hashes.
2. Index exact source excerpts. Let the model select excerpt IDs; code attaches the saved text and
   verifies offsets, hashes, claim IDs and source diversity. Invalid selections receive bounded repair.
3. Plan one narrative thread around 5–7 supported beats rather than catalogue every achievement.
4. Write near the middle of the configured range (750 words by default). Use a curiosity-building
   opening, concrete explanations, a beginning/middle/ending and a short History Detective note.
5. Deliver the first reading copy immediately. The chapter remains available during later stages.
6. Review concurrently: history checks support/certainty; narrative checks engagement and reading
   level; cultural review checks harmful framing. No role has a quota for findings.
7. Revise concrete material issues. Remove weak optional claims instead of adding speculative
   paragraphs. Supply the actual word count and target. Keep the best reviewed candidate so an
   unsuccessful revision cannot replace a better chapter.
8. Finish after the configured review limit or a reviewer outage. Save the selected `final.md`,
   export the clean chapter and retain unresolved findings. Optional minor notes do not veto delivery
   or mandatory AI checks. Critical/major issues prevent AI approval, not access to the draft.
9. Review all produced chapters together and save a book summary, including chapters needing review.

Technical API failures are recorded separately from editorial rejection. Existing chapters survive
review/revision outages. Research that cannot establish genuine source evidence still stops before
writing; the program does not fabricate history to guarantee a narrative under every failure mode.

Statuses include `AI_APPROVED_PENDING_HUMAN`, `CHAPTER_READY_NEEDS_REVIEW`,
`CHAPTER_READY_REVIEW_INCOMPLETE`, `BLOCKED_RESEARCH` and `FAILED_BEFORE_DRAFT`. Intermediate
reading copies may show `DRAFT_REVIEW_PENDING`. Exit `0` means every requested chapter was produced;
check the reports for editorial status. Exit `2` means some chapters were unavailable, `1` a startup
failure, and `130` cancellation. Human publication approval is always separate.

## Persistence, cost and limitations

The book/run archive retains sources, excerpt bindings, outline, every draft, reviews tied to draft
hashes, revision provenance, selected candidate, framework checkpoints, prompts and raw responses.
`current-run.json` points to the latest run. `execution.log` records real events; usage logs include
OpenRouter-reported cost when present. API keys and upstream error bodies are excluded from logs.
Output files contain book/research content and should be treated accordingly.

On restart, intact checkpoints can resume; otherwise stages reuse successful cached results. Results
can be imported across application versions only when exact request and output hashes match. New
prompts, Style Bible or content invalidate affected calls. Cached review data is revalidated and
rebound to the same draft; approval metadata and checkpoints are never imported across run versions.
Interrupted unsaved calls may repeat. One process at a time may use an output folder.

HTML/text source retrieval is supported, not PDFs, paywalls or JavaScript-only content. Retained
text is bounded. Exact excerpts establish provenance, not historical truth; model and human review
remain important. Model endpoints, schema support and account availability require live verification.
Reviewers receive focused context to limit cost and contradictory rewrites. Real OpenRouter
integration failures from the user's runs were diagnosed from saved responses, not concealed.

## Verification

The updated code builds with .NET 10, zero warnings/errors. No unit-test project was added. Offline
smoke harnesses outside the repository use real MAF agents/workflows with in-memory HTTP responses.
They verified instruction/schema forwarding, source/excerpt binding, bounded evidence repair,
checkpoint creation and completed-run cache recovery.

The redesigned delivery workflow was exercised across seven offline scenarios: approved chapter,
unresolved major findings, reviewer outage, failed revision, word-count correction, worsening
revision (the better candidate wins), and minor-only notes. All produced final chapter files with
honest approval status. Archive export was also checked for zero model calls and unchanged original
review records. These fixtures verify orchestration and delivery, not the quality of live model text.
No paid API calls were made by Codex. The user will verify live writing with their chosen models.
