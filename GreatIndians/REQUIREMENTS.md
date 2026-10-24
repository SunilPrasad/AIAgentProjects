# Updated Requirements — Fully Autonomous Book Writing Pipeline

## 1. Application execution

Build a .NET 10 C# Console Application using Microsoft Agent Framework.

The application must execute the entire book-writing pipeline automatically when started.

There must be no requirement to manually run commands for individual stages.

The user should only need to execute:

```bash
dotnet run
```

The application should load its configuration, identify the book and its chapters, and automatically orchestrate all required agents.

## 2. Automatic workflow

The complete execution sequence must be:

1. Load book configuration and permanent Style Bible.
2. Identify all historical personalities configured for the book.
3. For each personality, start the chapter-generation workflow.
4. Research the personality using genuine external sources.
5. Build and validate the historical Evidence Ledger.
6. Generate an engaging narrative outline.
7. Write the first chapter draft.
8. Send the draft to independent AI reviewers.
9. Analyse all review findings.
10. Automatically revise the chapter where necessary.
11. Repeat independent reviews after corrections.
12. Approve the chapter at the AI quality gate only when all mandatory checks pass.
13. Save the final chapter as a Markdown file.
14. Automatically continue to the next personality.
15. When all chapters are processed, generate a book-level editorial consistency review.
16. Produce a final execution summary.

Use Microsoft Agent Framework to orchestrate agent execution, dependencies, branching and review loops.

No manual intervention should be needed between automated stages under normal operating conditions.

If a critical historical issue cannot be resolved, mark the affected chapter as BLOCKED, save its findings, and continue processing other chapters.

Never silently approve unresolved problems.

A human approval step will be required later before publication, but must not prevent the automated generation of drafts for the entire book.

## 3. Live console output

While the application is running, display clear, real-time console output showing exactly what the agents are doing.

Use Microsoft.Extensions.Logging and optionally Spectre.Console for readable, coloured terminal output.

Example:

```text
==================================================
 GREAT INDIANS — AI BOOK WRITING FACTORY
 Microsoft Agent Framework | .NET 10
==================================================

[00:00:01] INFO   Loading book configuration...
[00:00:02] OK     Style Bible loaded successfully.

BOOK: Great Indians Who Changed History
AUDIENCE: Ages 8–12
CHAPTERS: 12
MODE: Automatic

--------------------------------------------------
CHAPTER 1/12 — ARYABHATA
--------------------------------------------------

[00:00:04] RESEARCH  Research Agent started.
[00:00:07] RESEARCH  Searching historical sources...
[00:00:14] RESEARCH  Collecting source references...
[00:00:22] RESEARCH  Evidence Ledger created.
[00:00:23] VERIFY    Validating source evidence...
[00:00:27] OK        Research package validated.

[00:00:28] PLAN      Story Planning Agent started.
[00:00:35] OK        Narrative outline generated.

[00:00:36] WRITE     Chapter Writing Agent started.
[00:00:52] OK        Chapter draft v1 saved.

[00:00:53] REVIEW    Independent historical review started.
[00:00:53] REVIEW    Children's narrative review started.
[00:00:53] REVIEW    Cultural sensitivity review started.

[00:01:10] REVIEW    Historical issue identified.
[00:01:10] WARNING   Claim: Aryabhata invented zero.
[00:01:10] REVIEW    Correction required.

[00:01:11] REVISE    Revision Agent started.
[00:01:24] OK        Chapter draft v2 saved.

[00:01:25] REVIEW    Rechecking revised chapter...
[00:01:39] OK        Mandatory AI checks passed.

[00:01:40] SAVE      Saving final Markdown chapter...
[00:01:41] COMPLETE  Aryabhata chapter completed.

--------------------------------------------------
CHAPTER 2/12 — CHANDRAGUPTA MAURYA
--------------------------------------------------

[00:01:42] RESEARCH  Research Agent started.
...

==================================================
 BOOK EXECUTION SUMMARY
==================================================

Chapters requested:    12
Chapters completed:    11
Chapters blocked:       1
Chapters needing human review: 1

Output directory:
output/GreatIndiansWhoChangedHistory/

Status: Completed with warnings
==================================================
```

The above is illustrative logging output. Actual messages must be generated from real workflow events rather than simulated progress.

Each log message should show:

- Timestamp
- Chapter name
- Agent name
- Workflow stage
- Current action
- Completion or failure status

Where available, also record model provider, model identifier, API token usage and estimated cost.

Do not expose API keys or sensitive information in console logs.

## 4. Automatic chapter processing

The book configuration must contain the list of personalities.

Example:

```json
{
  "bookTitle": "Great Indians Who Changed History",
  "audienceMinAge": 8,
  "audienceMaxAge": 12,
  "language": "British English",
  "chapterWordCountMin": 600,
  "chapterWordCountMax": 900,
  "personalities": [
    "Aryabhata",
    "Brahmagupta",
    "Chanakya",
    "Chandragupta Maurya",
    "Ashoka",
    "Swami Vivekananda",
    "Rani Lakshmibai",
    "Savitribai Phule",
    "Srinivasa Ramanujan",
    "C. V. Raman",
    "B. R. Ambedkar",
    "A. P. J. Abdul Kalam"
  ]
}
```

Automatically process every personality in the configured order.

Use sequential processing by default to minimise complexity and preserve deterministic progress.

Within a chapter, independent review agents may execute concurrently when their inputs are ready.

## 5. Persistence and recovery

Save all generated artifacts automatically.

Organise outputs by book and chapter.

Save:

- Research sources
- Evidence ledger
- Story outline
- Chapter versions
- Independent review reports
- Revision history
- Final chapter
- AI approval status
- Execution logs
- Model and prompt provenance

When the program restarts:

- Detect previously completed workflow stages.
- Resume incomplete chapters.
- Avoid unnecessary repeated model calls.
- Rerun affected stages when their inputs, Style Bible or prompt versions change.
- Never reuse an earlier approval for modified content.

Implement resumability using Microsoft Agent Framework checkpoints where supported, alongside durable application storage.

## 6. Error handling

Handle API errors, rate limits, invalid structured outputs, unavailable sources and agent failures.

Use bounded retries with exponential backoff for transient technical errors.

Do not confuse an API failure with an editorial rejection.

If a chapter repeatedly fails historical verification, mark it BLOCKED and continue with the next personality.

The application must never fabricate source material to overcome a research failure.

## 7. No unit tests for this version

Do not create a unit test project.

Do not implement xUnit, NUnit or MSTest.

Prioritise the working application, clear architecture, real agent integrations and complete execution logging.

However, the code must still be compiled successfully.

Verify package compatibility and perform a real end-to-end smoke run when valid API credentials are available.

Do not claim that external model integrations have been tested unless they were actually executed.

## 8. Scope of this phase

Produce TEXT ONLY.

Do not generate images, illustration briefs, PDF files, EPUB files or Amazon publishing files yet.

The goal is a complete, fully automated historical biography writing pipeline.

Future image generation and book assembly workflows will consume the approved chapter outputs.

## 9. Completion criteria

The application is successful when one execution automatically:

- Researches every configured personality.
- Produces evidence-backed narrative chapters.
- Uses independent AI models to review each chapter.
- Automatically performs necessary corrections.
- Saves every version and review report.
- Blocks chapters with unresolved critical problems.
- Performs a book-wide consistency review.
- Displays meaningful live progress in the console.
- Saves completed chapters as clean Markdown files.

The final output must be a collection of inspiring, engaging, historically responsible biographies suitable for children aged 8–12.

Implement this with real Microsoft Agent Framework .NET agents and orchestration, not a simulated multi-agent workflow.

Start by inspecting the existing C# repository, update the implementation to meet these requirements, and produce a working console application.