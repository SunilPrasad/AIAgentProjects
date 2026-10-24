# Great Indians — automatic text-only book pipeline

.NET 10 console application using Microsoft Agent Framework agents, typed workflow executors,
conditional review/revision edges and local framework checkpoints. All model calls go through
OpenRouter using one API key. Azure AI Foundry and direct OpenAI/Anthropic keys are not required.

## Run

From this repository's `GreatIndians/GreatIndians.Factory` directory:

```powershell
$env:OPENROUTER_API_KEY = "your OpenRouter API key"
dotnet run
```

Edit `book.json` to choose personalities, models, word limits and source requirements.
Edit `style-bible.md` to change the permanent editorial style. These files are loaded automatically.
An optional first argument selects a different configuration file: `dotnet run -- C:\path\book.json`.
The Style Bible and output paths are relative to that configuration file. Running from the project
folder uses its source `book.json`; the built executable falls back to the copied configuration.
Keys belong in environment variables, never configuration or source control.

The default configuration processes 12 personalities in order. For your first live run, reduce
`personalities` to one entry. Use OpenRouter model IDs (including the author prefix):

- `writerModel`: `openai/gpt-4.1` (ledger, planning, writing, revision, narrative review)
- `researchModel`: `openai/gpt-4.1` (web research)
- `reviewerModel`: `anthropic/claude-sonnet-4.5` (historical, cultural and book-wide review)

Evidence ledgers and review reports use explicit strict JSON schemas. OpenRouter routes these
requests only to endpoints that support the required response format; custom model choices must
support structured outputs. The adapter forwards MAF agent instructions as system messages, so
the Style Bible, task instructions and evidence rules reach each model.

All roles use OpenRouter Chat Completions, including Claude. Keep writing and review model IDs
different for model-independent review. Model availability depends on OpenRouter routing and your
account. Existing direct-provider model IDs such as `claude-sonnet-4-5` must be updated to the
OpenRouter IDs above when bringing over an older configuration.

Research uses OpenRouter's `openrouter:web_search` server tool with the Exa engine, bounded search
calls and optional domain filters. Search is billed through OpenRouter, with no separate Exa key.
It requires structured `url_citation` annotations from the search response before retrieving sources;
URLs merely mentioned by a model are not accepted. Search/tool unavailability or missing citations
blocks drafting for that chapter. The application still downloads each cited source separately and
validates ledger excerpts against the retained source text.

API reference: [Chat Completions](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion),
[web-search server tool](https://openrouter.ai/docs/guides/features/server-tools/web-search).
The search-tool API is currently beta. OpenRouter credits are required for model and search calls.

## What one execution does

1. Loads book configuration and Style Bible, then validates that the OpenRouter API key is present.
2. Searches the live web for each personality and downloads accessible public HTTPS HTML/text sources.
3. Saves source text snapshots, URLs, retrieval times and SHA-256 hashes.
4. Builds a structured evidence ledger. Rejects claims whose exact excerpts are absent from saved
   source text, and requires evidence from at least two source domains.
5. Creates an outline and a first Markdown chapter draft using real MAF AIAgents.
6. Runs historical, children's narrative and cultural sensitivity review agents concurrently.
7. Applies a deterministic word-count check. All reviewers must explicitly approve with no findings.
8. Routes rejected chapters through the MAF revision/review loop, up to the configured pass limit.
9. Saves AI-approved chapters as `final.md`, always pending human publication approval.
10. Marks unresolved historical/editorial issues BLOCKED; technical failures are recorded separately.
    Both allow the next personality to proceed.
11. Reviews the approved chapters together for book-wide editorial consistency and saves a summary.
    Book-wide findings remain visible and keep the book from passing its overall AI gate.

No images, illustration briefs, PDF, EPUB or publishing files are generated.

## Recovery and outputs

The output tree is organised by book, input/application version and chapter. `current-run.json`
points to the current version. All earlier version directories are retained. Each chapter stores:

- `research/`: search response, sources and evidence ledger
- `outline.md` and `drafts/`: planning and all editorial draft versions
- `reviews/`: individual reviews and quality gates bound to the reviewed draft hash
- `revisions/`: before/after hashes and findings used for revision
- `provenance/`: actual prompts, model identifiers and raw provider responses (no API keys)
- `checkpoints/`: Microsoft Agent Framework filesystem checkpoints
- `cache/`: input/output-hashed successful stage results
- `status.json`, `failure-details.json` when a chapter fails, and, only on approval, `final.md`

Console messages reflect actual workflow activity. `execution.log` also retains those events;
raw responses contain provider token usage. Reported OpenRouter cost is logged when supplied;
otherwise cost is explicitly reported as unavailable rather than guessed. Provider error bodies and API keys are excluded from logs.
Prompts and source snapshots contain book/research content; treat the output folder accordingly.

On restart, intact in-progress chapters restore their MAF checkpoint. If artifacts changed, or a
chapter previously completed/failed, the graph re-enters through the application stage cache and
revalidates its results. Completed successful calls with identical inputs do not repeat. Changes to
configuration, Style Bible or compiled application invalidate the run namespace conservatively.
Unchanged research search/source caches can be imported from earlier runs of the same chapter when
both exact request and content hashes match. Imported provenance points to the retained original
artifacts. Drafts, approvals and checkpoints are never imported across run versions.
Changing a draft never transfers its earlier review approval to the changed text. Interrupted calls
that did not durably save a successful result can repeat. Failed requests have bounded exponential
backoff; 429/5xx/timeouts are distinguished from editorial rejection. Ctrl+C saves completed stages.
Only one process can use an output directory at a time.

Exit codes: `0` all chapter and book AI gates passed (human approval still pending); `2` completed
with blocked chapters, technical failures or book findings; `1` startup/unhandled failure; `130` cancelled.

## Practical limits and verification

Exact excerpt matching verifies provenance, not historical truth. Independent reviewers assess
whether claims follow from excerpts, but human editorial approval remains necessary before publication.
The source downloader supports HTML/text, not PDFs, paywalls or JavaScript-only pages, and retains a
bounded text snapshot. Insufficient accessible evidence blocks a chapter instead of inventing support.
`allowedSourceDomains` optionally restricts discovery and retrieval; an empty list searches broadly.
Different domains alone do not prove editorial independence or scholarly reliability.

The updated application was built successfully with .NET 10.0.103, with zero warnings/errors.
No unit test project was created. No paid API calls or live end-to-end run were executed by Codex: the user
will perform the live smoke run with an OpenRouter API key. An offline regression smoke check against a user-supplied saved search response verified source URL
discovery, nested exception unwrapping and research cache reuse/invalidation. This did not make
model calls. A further offline smoke check exercised real MAF agents through an in-memory HTTP
handler, verified instruction/schema forwarding and corrective retries against saved invalid prose,
then ran the full workflow graph to final Markdown, checkpoints, book review and a cache-only
restart using fixture outputs. These checks validate application plumbing, not model quality or
live OpenRouter schema enforcement. Recovery and remaining provider behaviour are implemented
but remain to be verified during that run. See `REVIEW.md` for findings in the original prototype.
