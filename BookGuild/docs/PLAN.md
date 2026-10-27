# Book Guild — Multi-Agent Book Creator (Windows 11 desktop app)

## Context
You want a Windows 11 desktop app that takes a book from idea to files you can sell: KDP paperback, Kindle EPUB and an Etsy PDF. Every stage is done by AI agents through OpenRouter. Important stages use **3 drafting agents plus a jury**, you approve at key gates, and progress, logs and cost are visible all the time. The cost for a 100-page book must stay low. The code should be easy to read: plain modules, no heavy framework layers.

The working directory `C:\Codex\book-creator` is empty, so this is a new project.

**Decisions made**
- Stack: **Python 3.12 + PySide6** (Qt) desktop app. Async work runs through `qasync` and HTTP through `httpx`.
- LLM and image generation: **OpenRouter** only. Models are set in config (a cheap tier and a strong tier).
- Web research: choose a **cheap search provider**. The default is a free one, behind a small provider interface (see Research below).
- Agent naming theme: **Guild of the Book**.
- Outputs: KDP paperback (interior PDF + wrap cover PDF), Kindle EPUB and Etsy PDF.
- Your gates: **Book Profile + Title/Outline**, **every image**, **cover**. Chapters are accepted automatically by the jury, but you can reopen any chapter.
- First book type to perfect: **evidence-based non-fiction**. Fiction, children's and workbook modes come later.

---

## The Guild (agents and agent groups)
| Name | Kind | Job |
|---|---|---|
| **Steward** | single | Reads your chat messages and turns them into app actions (approve, redo chapter 3, change tone, show cost) |
| **Cartographer** | single | Drafts the **Book Profile** from your idea |
| **Scouts** (Scout-1/2/3) | group of 3 | Web research. Each produces a research brief with sources |
| **Architects** (3) | group of 3 | Each proposes a title, subtitle and chapter outline |
| **Scribes** (3) | group of 3 | Each writes a full draft of the current chapter |
| **Council** (3 jurors + Chair) | jury | Scores the competing drafts against a rubric. The Chair picks the winner and writes a short revision note |
| **Archivist** | single | Fact-checks the winning chapter against the Scouts' sources and flags unsupported claims (evidence mode) |
| **Curator** | single | Finds or generates image candidates for each chapter and records each image's license |
| **Illuminator** | single | Produces the cover concepts, cover art and back-cover blurb |
| **Binder** | non-LLM | Typesets and exports the PDF, EPUB and cover |

Each agent shows up in the UI with its name, current status (idle/thinking/done/failed), model, tokens used and cost.

## Book Profile (how one app handles different styles)
The Cartographer creates `profile.json`, and you edit or approve it. Every agent prompt includes it.
- `mode`: `evidence` | `fiction` | `children` | `workbook`
- `audience_age`, `reading_level`, `tone`, `voice` (1st/2nd/3rd person)
- `citations_required` (true in evidence mode), `fact_check` (on/off)
- `image_strategy`: `licensed_web` | `ai_generated` | `mixed` | `none`, plus `images_per_chapter` and `image_style`
- `target_pages`, `words_per_page`, `chapter_count`, `trim_size` (e.g. 6x9), `paper` (white/cream), `formats`
- `budget_usd`: a hard cap. The pipeline pauses when it is reached

Each mode is a small **prompt pack** (a folder of prompt templates). Adding a mode means adding a folder, not new code paths.

## Pipeline (stages)
0. **Brief**: you start a book with a free-text brief (`brief.md`) covering your idea, audience, style and example passages you like. The title is optional
1. **Profile**: the Cartographer drafts the profile from your brief → **you approve**
2. **Research**: 3 Scouts research the topic from different angles → the briefs are merged into `research/topic.md` with a source list
3. **Outline**: 3 Architects propose an outline → the Council picks one → **you approve** (or edit the title or chapters)
4. **Chapters** (looped per chapter, independent chapters can run in parallel):
   a. Scouts do focused research for the chapter (evidence mode)
   b. 3 Scribes write drafts → the Council scores them → the winner is revised once using the Chair's note
   c. The Archivist fact-checks it (evidence mode). Unsupported claims are fixed or removed
   d. The chapter is marked approved. You can reopen it from chat or the UI
5. **Images**: the Curator searches licensed sources (Wikimedia Commons, Openverse, Pexels, Pixabay, Unsplash) and/or generates images with AI → **you approve or reject each one**. Only approved images are placed
6. **Cover**: the Illuminator makes 3 concepts → **you pick one** → final front art, then the Binder builds the wrap with the spine
7. **Export**: the Binder produces the KDP interior PDF, KDP cover PDF, EPUB and Etsy PDF, plus a listing sheet (title, subtitle, description, keywords, categories)

Every stage is **resumable**: state lives on disk, so you can close the app and continue later. Every stage can also be **rerun**.

## Jury mechanics (kept simple)
- Each juror gets all 3 anonymised drafts (A/B/C) plus a rubric. The rubric weights depend on mode: accuracy/evidence, audience fit, clarity, structure, engagement and profile adherence.
- Each juror returns strict JSON with scores, a ranking and a one-line reason for each draft.
- The ranks are summed (Borda count) and ties are broken by total score. The Chair (strong model) confirms the result and writes a revision note.
- The draft order is shuffled for each juror to reduce position bias. Jurors use **different models** from the Scribes where possible.

## Model strategy (diverse writers and jury, cheap testing)
- **Model profiles** in `settings.toml`, switchable from the UI:
  - `test`: the cheapest or free OpenRouter models for everything. Used during development and phase testing.
  - `balanced`: cheap and mid-tier models. The default for real books.
  - `quality`: frontier models for the Chair and the Archivist.
- **Provider diversity is enforced:**
  - Each Scribe uses a model from a **different provider** (e.g. DeepSeek / Qwen / Google).
  - Council jurors use providers that **are not used by any Scribe** (e.g. Anthropic / OpenAI / Mistral).
  - The config validator refuses a setup where a juror shares a provider with a Scribe.
- **Draft count is configurable** (3 by default, up to 5).
- Model names and prices are **not hard-coded**. The app reads OpenRouter's `/api/v1/models` list, so you pick from current models and see their real prices.
- **Experiment in Phase 6:** on the same chapter, run (a) 5 drafts from cheap models and (b) 3 drafts from mid/frontier models. Compare the jury scores, fact-check flags and $ cost, then you choose the default from the data.

## Research quality (evidence mode)
Search quality decides book quality, so evidence mode uses a **layered research stack**:
1. **Primary web search:** **Tavily (advanced depth)** or **Exa**. Both return full page text and are built for research. Expect about 150–300 searches per book, roughly $1–3 per book. Tavily's free tier of about 1,000 searches a month covers testing.
2. **Scholarly sources (free APIs):** OpenAlex, Crossref, Semantic Scholar and the Wikipedia API, for papers, DOIs and established facts.
3. **DuckDuckGo:** used **only** in the `test` profile or as a last fallback, never as the main source for evidence books.
- **Source quality scoring:** .gov, .edu, journals and established publishers rank higher. Content farms and AI-spam domains go on a blocklist.
- Every claim in a chapter carries a source id. The **Archivist requires at least 2 independent sources** for key facts and flags single-source claims.
- The Research view shows each source with its quality score, so you can **exclude a bad source** before writing starts.

## Images: budget-friendly licensed providers
`research/search.py` defines `SearchProvider.search(query) -> list[Result]` with these implementations: Tavily, Exa, OpenAlex, Crossref, Semantic Scholar, Wikipedia and DuckDuckGo. Page text is extracted with `trafilatura` when a provider doesn't return it.

Images come **only from commercially licensed sources**: the Wikimedia Commons API, the Openverse API (CC0/PD filter), Pexels, Pixabay and Unsplash, all free with a key. Each image stores its source URL, author and license in `images/manifest.json`, and the export can produce an image-credits page. AI images come from an OpenRouter image model (e.g. a Gemini image model) and their model is recorded.

## Your own images (user-provided)
- You can upload images anywhere an image is needed: **front cover art, back cover art**, and any chapter image slot.
- Uploaded images count as **pre-approved**. They get license `user-provided` in the manifest and **skip AI or web lookup for that slot**, which saves cost.
- Cover: if you upload a front or back image, the Illuminator only adds the title, subtitle, author and blurb text layout on top. It does not generate art for that side.
- Quality check: the Binder warns if an image is below 300 DPI at its printed size, and if cover art does not match the trim plus bleed size.

## Reliability: retries, failure highlighting, no token-burning loops
- **One wrapper for every LLM, search and image call** (`bookguild/reliability.py`):
  - Retries **at most 3 times** with exponential backoff (2s → 4s → 8s), and only for transient errors (timeouts, 429, 5xx, invalid-JSON replies).
  - Errors that won't fix themselves fail immediately with no retry: bad API key, insufficient credits, model not found, content refused.
  - After the retries, it can make **one fallback model attempt** (configured for each tier), then it fails.
- **Hard limits for each stage**, set in config:
  - `max_attempts_per_step` (e.g. 3)
  - `max_revision_rounds` (e.g. 1 for a chapter, so there is never a rewrite → re-judge → rewrite loop)
  - `max_stage_cost_usd`
  - `max_stage_minutes`
  - Hitting any limit **stops that step and marks it FAILED**. There are no silent retries beyond the limits.
- **Circuit breaker:** if 3 consecutive calls fail across the pipeline (e.g. OpenRouter is down), the whole pipeline **pauses** and asks you what to do.
- **Partial success is allowed:** if 1 of 3 Scribes fails, the Council judges the 2 drafts it has. If fewer than 2 drafts survive, the step fails.
- **How failures show up:**
  - The stage turns red on the timeline and the agent card turns red with the error.
  - A **Failures panel** lists each failure with its stage, agent, error message, attempts and cost spent, plus **Retry**, **Skip** and **Edit & retry** buttons.
  - Each failure is also written to `log.jsonl` with full context (prompt id, model, HTTP status).
- **Checkpointing:** every completed sub-step is saved to disk before the next one starts. A retry resumes from the failed step, so finished work is never paid for twice.

## Cost estimate (100 pages ≈ 25k words, 10 chapters, evidence mode)
- Scribes 3×: about 100k output tokens plus about 200k input (research context)
- Council: 3 jurors × 10 chapters × about 10k input tokens is about 300k input, plus Chair calls
- Research and fact-check: about 300k input
- Cheap models (about $0.1–0.5 per M input, $0.5–2 per M output) for Scouts, Scribes and jurors, and a strong model only for the Chair and Archivist: **about $1–4 for text**
- Images: licensed web images are $0. AI images cost about $0.03–0.05 each, so 30 images is about $1–1.5. A cover costs about $0.2
- **Target: under $5 per 100-page book.** The live cost meter reads the real per-call cost from OpenRouter's `usage` field, and the pipeline stops at `budget_usd`

## UI layout (PySide6)
```
┌───────────────────────────────────────────────────────────────┐
│ Library (books) │  STAGE TIMELINE  Profile ▸ Research ▸ ... ▸ Export │ Cost $1.23/5 │
│                 ├──────────────────────────────────────────────┤
│                 │  GUILD BOARD: agent cards (Scout-1 ● thinking…) │
│                 │  CENTRE: current stage view                      │
│                 │   - outline compare / chapter drafts + jury scores│
│                 │   - image approval grid (✓ / ✗)                  │
│                 │   - cover picker                                  │
│                 ├──────────────────────────────────────────────┤
│                 │  LOG (filter by agent/stage)                      │
├─────────────────┴──────────────────────────────────────────────┤
│  Chat with Steward ▸ "redo chapter 4, more examples for teens"  │
└───────────────────────────────────────────────────────────────┘
```

## Project layout (readable, flat)
```
book-creator/
  app.py                    # entry point
  pyproject.toml
  config/settings.toml      # API keys (via env/keyring), model tiers, providers
  bookguild/
    llm.py                  # OpenRouter client: chat(), json_chat(), image(); returns text + cost
    events.py               # EventBus (Qt signals): agent_status, log, cost, stage_changed
    storage.py              # book folder read/write helpers
    budget.py               # cost tracking + cap
    reliability.py          # retry/backoff, error classes, fallback model, circuit breaker
    agents/
      base.py               # Agent dataclass: name, role, model, prompt template, run()
      guild.py              # instantiates the named agents from config
    stages/                 # one file per stage, each a plain async function
      profile.py research.py outline.py chapters.py images.py cover.py export.py
    jury.py                 # council voting (used by outline + chapters)
    research/search.py      # search providers + page extraction
    images/sources.py       # Wikimedia/Openverse/Pexels/Pixabay/Unsplash
    export/                 # typst templates, epub builder, cover/spine calc
    prompts/<mode>/*.md     # prompt packs per book mode
    ui/                     # main_window.py, timeline.py, guild_board.py, log_view.py,
                            # chat_bar.py, views/ (outline, chapter, image_grid, cover)
  tests/
```
**Book folder on disk** (`Documents/BookGuild/<book-slug>/`): `profile.json`, `state.json` (stage progress), `research/`, `outline.json`, `chapters/01-draft-A.md … 01-final.md`, `jury/01.json`, `images/` + `manifest.json`, `cover/`, `exports/`, `log.jsonl`, `costs.jsonl`. These are plain files you can open and read.

## Export technology
- **Typst** (via the `typst` pip package, no external install) for the interior PDF and cover PDF. It gives exact trim size, margins, 0.125" bleed and the KDP gutter for the page count.
- Spine width = pages × 0.002252" (white) or 0.0025" (cream). The wrap cover is back + spine + front + bleed.
- **EPUB** via `ebooklib` from the same chapter Markdown.
- **Etsy PDF** uses the same Typst template with Letter/A4 page size.

## Code-style rules
- Stages are plain `async def run(book, guild, bus)` functions. There is no plugin registry or DI container.
- Agents are data plus one `run()` method. Prompts live in Markdown files, not code.
- The UI only listens to EventBus signals and calls stage functions. No business logic in widgets.
- Type hints, small modules, and a docstring at the top of each stage explaining what it does.

## Phased delivery plan
We build **one phase at a time. I stop after each phase**, you test it and give feedback, I apply the feedback, and only then do we move on. All phase testing uses the `test` model profile (the cheapest models). Each phase ends with a demo you run yourself and a checklist you tick off. **The next phase starts only after you confirm the checklist.** Every phase also ships with its tests and works in **dry-run mode** (fake LLM, $0).

### Phase 0: Project setup
- **Build:** `pyproject.toml`, virtual env, folder layout, `git init`, `settings.toml` template and a README with run steps.
  - The OpenRouter API key is **read from your Windows environment variable**. The default name is `OPENROUTER_API_KEY`, and you can change the name in settings.
  - Keys are never written to disk or to logs.
  - Optional keys (Tavily, Pexels, Pixabay, Unsplash) are read from environment variables the same way.
- **You verify:**
  - `python app.py` opens an empty window. `pytest` passes.
  - The app reports "OpenRouter key found" or, if it's missing, shows a clear red error.

### Phase 1: Skeleton UI + core plumbing
- **Build:**
  - Main window layout: library, stage timeline, Guild Board, centre area, log, chat bar and cost meter.
  - EventBus, the log view (filter by agent/stage), book folder create/open, and the settings dialog.
- **You verify:** you can create a "Test Book" and see its folder on disk. Fake log events show in the log panel. The UI stays responsive.

### Phase 2: OpenRouter client + reliability + cost
- **Build:**
  - `llm.py` (chat, JSON chat, image), `reliability.py` (retry/backoff, error classes, fallback model, circuit breaker), `budget.py`, and the Failures panel.
  - A "Test connection" button that runs one real cheap call.
  - Model profiles (`test` / `balanced` / `quality`), a model picker that loads OpenRouter's live model list and prices, and the provider-diversity validator.
- **You verify:**
  - A real call shows its tokens and $ cost.
  - A wrong key shows a red failure with **no** retries.
  - A simulated timeout retries exactly 3 times, then shows FAILED with Retry and Skip buttons.
  - The budget cap stops calls.

### Phase 3: Book Profile + Steward chat
- **Build:** the Cartographer turns your idea into a profile, a profile editor form, the approval gate, and Steward chat commands (approve, edit field, show cost, status).
- **You verify:** typing an idea in chat produces a sensible profile, you can edit and approve it, and `profile.json` is saved.

### Phase 4: Research (Scouts)
- **Build:**
  - The layered research stack: Tavily/Exa, the scholarly APIs, and DuckDuckGo for the test profile.
  - Source quality scoring and blocklist.
  - 3 Scouts with different angles.
  - A merged brief with numbered sources.
  - A research view where you can exclude a source.
- **You verify:**
  - A topic produces a readable brief with real, clickable, good-quality sources.
  - You can exclude a source.
  - One Scout failing still produces a brief from the others.
  - We compare the brief's quality from Tavily vs Exa vs DuckDuckGo on the same topic.

### Phase 5: Title & outline (Architects + Council)
- **Build:** 3 Architects, `jury.py` (Borda count + Chair), and an outline comparison view showing jury scores and reasons. You can approve, edit or rerun.
- **You verify:** you can see all 3 proposals side by side, see why the winner won, edit chapter titles and approve.

### Phase 6: Chapter writing (Scribes + Council + Archivist)
- **Build:**
  - Per-chapter research, 3 Scribes, judging, one revision round and the Archivist fact-check.
  - A chapter viewer with the drafts, scores, final text and flagged claims, plus a "reopen chapter" command.
- **You verify:**
  - A 3-chapter test book completes.
  - The cost per chapter is shown.
  - A forced failure on one chapter doesn't block the others.
  - The limits stop any looping.

### Phase 7: Images (Curator + your uploads)
- **Build:** licensed source search, AI generation, the approve/reject grid, **upload your own image** into any slot, `manifest.json` with licenses, and the DPI check.
- **You verify:** only approved and uploaded images appear in the chapters, rejected ones are gone, and the credits list is correct.

### Phase 8: Cover (Illuminator + your uploads)
- **Build:**
  - 3 cover concepts and a picker.
  - **Upload your own front and/or back cover image.**
  - Title and blurb typography, and the wrap cover with spine calculation.
- **You verify:**
  - Picking a concept or uploading a front/back image gives a correct wrap cover preview.
  - The spine width matches KDP's calculator for that page count.

### Phase 9: Export (Binder)
- **Build:** the Typst interior PDF (trim, margins, gutter, bleed, TOC, page numbers), the KDP cover PDF, the EPUB, the Etsy PDF and the listing sheet.
- **You verify:** the PDF and cover pass the **KDP previewer**, the EPUB opens in **Kindle Previewer**, and a full 100-page test book costs less than the target.

### Phase 10: More book modes
- **Build:** the fiction, children's picture book and workbook prompt packs, plus mode-specific rubrics and layouts.
- **You verify:** one short sample book of each mode.

## Verification
- Unit tests (`pytest`) for jury aggregation, spine/cover math, budget cap, profile validation and prompt rendering. These use a fake `llm.py` that returns canned replies.
- A "dry-run" mode with a fake LLM, so the whole pipeline and UI can run for free.
- After each phase, launch `python app.py`, run that stage on a small test book (e.g. a 3-chapter evidence book on "The History of Tea") and check the UI updates, logs, costs and files on disk.
- Final check: upload the exported PDF and cover to KDP's previewer and the EPUB to Kindle Previewer to confirm they are accepted.
