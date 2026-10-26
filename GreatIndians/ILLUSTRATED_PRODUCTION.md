# Illustrated chapter production

This is a separate production command for the existing researched Markdown chapters. It never runs the research/writing pipeline and never asks a model to rewrite the manuscript. The supplied [master requirements](PRODUCTION_REQUIREMENTS.md) are retained in full. PDF chapter production is implemented here; reflowable EPUB generation is included by default, with Kindle preview explicitly still required. Full-book assembly and cover/spine production remain separate work.

## Run one chapter

If the cheaper draft image model rejects a request with HTTP 400, 404 or 422, production records the provider error and tries the configured main image model once for that same attempt. Safety/moderation rejections and authentication/billing errors do not trigger this fallback. Every returned image still needs the normal image review. An unchanged rerun reuses the recorded draft rejection and any accepted fallback image. HTTP error details are retained under `provenance/*-http-error-*.json`; the console includes the provider's error message instead of only “Bad Request”. If the main model also rejects the request, production stops with that detailed error.

From `GreatIndians/GreatIndians.Factory`, first inspect the selected source without spending credits:

```powershell
dotnet run -- pdf --chapter Bhaskaracharya --inspect
```

Then create its illustrations and reviewed PDF:

```powershell
$env:OPENROUTER_API_KEY = "your OpenRouter key"
dotnet run -- pdf --chapter Bhaskaracharya
```

Use the exact subject from the chapter title, or an explicit Markdown file path. Quote names containing spaces. To process all saved final chapters:

```powershell
dotnet run -- pdf --all
```

EPUB is enabled by default to match the full master prompt. To enable it explicitly when using a PDF-only configuration:

```powershell
dotnet run -- pdf --chapter Bhaskaracharya --epub
```

Paths and model choices are in `production.json`. `--config C:\path\production.json` selects another configuration; paths inside it resolve relative to that file. Defaults read `../output/final-chapters` and write `../output/illustrated`. The original `dotnet run` writing command remains available.

## Production and review

1. Parse the saved manuscript into paragraphs with stable IDs and preserve inline italics/bold. Retain an unchanged Markdown snapshot and source SHA-256. Preserve original section headings at 14pt bold, left-aligned, beneath the visual hierarchy of the 22pt main title. Keep headings with the following paragraph, verify their text/order in PDF and EPUB, and list them in QA. Reject unsupported markup rather than silently losing content. The main chapter title appears only once.
2. Read the complete manuscript to plan 4–7 distinct passage-linked illustrations and a subject-specific character reference. Validate the exact subject, ordered paragraph anchors and aspect ratios.

   The application binds scene identity from the validated manuscript/character, links an unanchored opening portrait to P001, and derives invalid layout positions from the scene's existing source paragraph IDs. These metadata adjustments are logged in `reviews/plan-*-validation.json`; scene descriptions and manuscript text remain unchanged. A different historical identity or nonexistent evidence paragraph still fails validation. The original model responses remain in provenance, and compatible cached plans can be reused without another model request.
3. Generate and independently review I01 first, then reuse the approved opening artwork as the character reference for later scenes. The author-supplied image in assets/reference/art-style-reference.png guides palette and brushwork only; it never supplies the historical identity. Review the actual pixels for subject, head/headwear/important-object cropping, anatomy, unwanted text, historical plausibility, passage alignment, consistency, visual style and sharpness. Rejected images regenerate with review feedback, up to the configured attempt limit.
4. Typeset real selectable text at 6 × 9 inches, with one main chapter headline, a chapter number and page numbers. Liberation Serif fonts are embedded. The latest [master design specification](DESIGN_SPECIFICATION.md) supersedes the earlier reference PDF: ivory #FFFDF6; 12.1pt body #1D2636 with 17pt default leading; 22pt bold title #0C348B; 10pt bold chapter label #B16A14; 9pt regular page numbers #213A73. Opening artwork is 3:2 landscape. Images use proportional contain placement, without cropping or stretching, at 300+ effective PPI.
5. Extract the finished PDF text and compare every page and paragraph with the source, allowing only layout whitespace, the chapter number and page numbers. Verify trim size, safe text/image bounds, gutter, font embedding and image resolution. Actual selectable PDF glyphs are checked for Liberation Serif, the specified point sizes, heading weights and exact text colours.
6. Render **every page** and send each rendered page to the vision reviewer with its exact expected text and passage/image mapping. Review text legibility, overflow, clipping, image/text overlap, headings, subjects and illustration alignment. A failed layout gets a bounded retry with smaller images; unresolved issues retain a preview and report.
7. Recheck original source and artwork hashes before promoting the reviewed preview to the final filename. Never regenerate the biography to repair a layout or image problem.

Successful status is `PDF_REVIEW_PASSED`. This means the automated production checks passed; it is not a claim of historical certainty or KDP publication approval. AI visual review can miss defects. Inspect page proofs before publication. If an illustration or review service fails, `REQUIRES_ATTENTION` and `QA.md` explain what remains; cached stages and previews remain available for diagnosis/resume.

## Output

Each chapter has its own directory and an input-hash subdirectory. Changed manuscripts/configuration/style produce separate runs, preventing stale approvals from attaching to new inputs. Prompts, model IDs, image bytes and review inputs are hashed for cache reuse. API keys are never written to provenance.

```text
output/illustrated/chapter_09_bhaskaracharya/<input-hash>/
  chapter_09_bhaskaracharya_print.pdf   # promoted only after PDF review passes
  chapter_09_bhaskaracharya.epub        # enabled by default; Kindle preview still required
  source.md
  manuscript.json
  illustration-plan.json
  illustrations.json
  chapter_09_artwork/                 # delivered, reviewed image assets
  chapter_09_illustrations.json       # passages, print placement and review decisions
  chapter_09_QA.md
  artwork/                           # retained generation attempts
  reviews/
  pages-1/                            # every rendered page
  preview-1.pdf
  layout-1.json
  text-checks-1.json
  page-reviews-1.json
  provenance/
  cache/
  status.json
  QA.md
```

The command logs the full final PDF path. `status.json` is the authoritative outcome of the most recent invocation. Failed proofs are not final deliverables. Cached reviews are reused only for identical prompt/context and image hashes.

EPUB uses real XHTML paragraphs, emphasis, responsive images, alt text and navigation. Its reopened paragraph text is checked against the manuscript. It has no fixed PDF page numbers. EPUBCheck and Kindle Previewer/device validation are not performed by this command and must be completed before Kindle publication.

## Models, costs and scope

All calls use one OpenRouter key. Defaults:

- Planning: `openai/gpt-4.1`.
- Artwork: `google/gemini-3-pro-image`, 2K. Later scenes first try the cheaper `draftImageModel` (`google/gemini-nano-banana-2.1`, about a quarter of the price per image). Retries, and always the final attempt, use `imageModel`. Each candidate faces the same scored review, so the acceptance bar does not change. Set `draftModelForOpening: true` to draft I01 as well, or `draftImageModel: ""` to turn drafting off.
- Image and rendered-page review: `anthropic/claude-sonnet-4.5`. `pageReviewModel` can override the page reviewer.

### Cost controls

- `pageReviewScope: "illustrated"` (the default) sends the opening page, every page with artwork and the final page to the vision reviewer. Text-only pages rely on the exact text comparison, overflow and sparse-page checks. Use `"all"` to review every page.
- `reviewImageMaxEdge: 1024` sends reduced JPEG copies of artwork to the image reviewer. Print artwork is never altered. Later scenes are style-checked against the accepted I01, which already passed review against the art-style reference.
- `editNearMissImages: true`: when a rejection was close (within 15 points, right subject and passage), the retry edits that image rather than starting a new composition. This targets local defects such as stray script or a beard.
- After I01 is accepted, its reviewed `visibleIdentity` (hair, facial hair, age, clothing) is locked into every later prompt. The planner avoids scenes whose writing surfaces face the viewer. These were the two most common reasons for regenerations.
- `maxBookCostUsd` (0 = unlimited) stops before the next paid image once this invocation has spent that much. Re-running resumes from saved results.
- The cost of every chapter is printed when it finishes and is written to `status.json`, `QA.md` and `cost-summary.json`. The text factory (`chapters/*.status.json`, `execution-summary.json`) and topic discovery (`status.json`) do the same. Results reused from cache cost nothing and are shown as such.
- A warning is logged when the image provider returns a smaller resolution than `imageResolution` requested.

The image adapter uses OpenRouter's [dedicated image API](https://openrouter.ai/docs/guides/overview/multimodal/image-generation). Planning/review use structured JSON responses. Provider availability and costs can vary. A four-illustration chapter requires four image generations, four image reviews, a planning call, and one vision call per PDF page; retries add calls. The approved opening image doubles as its character reference, removing one generation and one review (20% fewer base image-generation calls). Google Pro remains the default. Usage returned by OpenRouter is logged. `--inspect` makes no API calls.

Set `bookPageCountForGutter` to the anticipated **whole book** page count when known. Zero uses approximately 0.76-inch side margins matching the reference text column, but the assembled book still needs its actual gutter checked. Standalone chapters do not establish KDP minimum book length, cover/spine dimensions, full-book pagination, colour/print-profile suitability or physical proof quality. No scientific diagrams are generated by AI; existing formulas remain selectable text, and any future added scientific diagram needs deterministic construction and its own validation.

The renderer is pinned to PDFsharp 6.2.4 (MIT); newer 6.5 releases change licensing. Bundled Liberation Serif font terms are in `GreatIndians.Factory/assets/fonts/Liberation-LICENSE.txt`. PDF rendering uses PDFium/SkiaSharp native assets restored by NuGet; Windows x64 is the verified development platform.

Matching stage results can be reused across earlier run folders for the same chapter only when their complete input/output hashes agree, including model, source, full prompts and all reference-image hashes. A line-spacing-only configuration change can reuse artwork while rendering and reviewing the changed PDF afresh. A changed visual style requires new art; previous approved output stays in its original folder.

## Design authority

ProductionDesign.cs is the shared definition used for print layout, EPUB CSS and page-review instructions. Each run records its version and settings in design.json. The command logs the applied font, size, leading and paper colour before paid calls. --inspect also shows the design without API calls. Body font size is fixed at 12.1pt; configuration is rejected if it would shrink the text or move leading outside 16.5–17.5pt. The written master controls typography, safety and the palette. The supplied art reference controls the intended saturation, golden lighting, dimensional painted detail and atmospheric finish.

### Reference matching and balanced pages (reference-balanced-v4)

The approved opening image establishes the adult character's visual identity. Later images use that actual appearance even when the speculative written character sheet differs. A clearly different person or major unexplained change in facial hair remains a defect; small differences in hairstyle, clothing shade/draping and apparent adult age are acceptable compromises.

Image review now uses `scored-review-v5`: `minimumImageScore` defaults to **70/100** in `production.json` (configurable from 70 to 95). The total is 40% style, 30% character and 30% quality, with each category at least 50. Scores of 70–79 mean usable with minor compromises, 80–89 strong, and 90–100 excellent. Contour lines or less dimensional fabric shading can pass. Soft matching booleans and the reviewer's overall `Approved` opinion are diagnostic; the code decides from scores and mandatory defect checks. Missing comparisons or scores still fail.

Wrong subjects, cropped heads/important features, generated writing, significant anatomical errors, clear anachronisms, unsupported scenes, clearly inconsistent characters and unusable sharpness cannot be offset by a high score. Hard reasons go in `issues`; soft improvements go in `suggestions`, which are retained in the review and final artwork manifest. Final page review must not reopen accepted soft image differences. The first image meeting the threshold is accepted immediately, without buying extra attempts to chase perfection. Rejected scenes alone are retried up to `maxImageAttempts`.

The first opening-image generation prompt is unchanged by this policy update, so an identical cached I01 can be reused and rescored instead of regenerated. Scored reviews are new calls; unchanged planning results can also be reused. Later image prompts now explicitly prioritise the accepted character image. No existing image is accepted without its new scored review. Actual model judgements still need the author's final visual approval.

Before paid page reviews, the renderer compares four local layouts. It can modestly resize complete illustrations at their existing narrative anchors, uses 8pt paragraph gaps and a 54pt continuation-page top margin, and scores page count and excess whitespace. It never crops images, changes manuscript order, shrinks text or changes configured leading. A nearly empty final continuation page (fewer than six body lines, without artwork) fails deterministic checks and triggers the remaining layout attempt before finalisation. Only the selected proof is sent for vision review, so local comparisons add no API calls.

The new prompt/design versions create a separate run folder. Older artwork reviews do not meet the new required review fields; changed image prompts require new artwork. Existing story files and previous output folders remain intact. Run `dotnet run -- pdf --chapter Baudhayana` from `GreatIndians.Factory` as usual.

## Verification performed

Offline layout checks used all ten current manuscripts and geometric placeholder images: source paragraph order and text matched PDF/EPUB, fonts were embedded, images exceeded 300 PPI, and all PDF pages rendered. An injected offline HTTP handler exercises planning, image generation/review and page-review wiring, including refusal to finalise cropped images. These fixtures are not historical illustrations or evidence of real vision-model accuracy. Live paid generation and review are left for the user's run.

Run the committed native layout and review-gate regression checks from the repository root:

```powershell
dotnet run --project GreatIndians/tests/Production.RegressionTests
```

The tests use geometric placeholders and generated text fixtures, verify exact PDF/EPUB text and aspect ratios, check illustration anchors and sparse-page rejection, and reject missing character/style review evidence. Pass a directory containing ten retained Markdown chapters after `--` to exercise those manuscripts instead. They make no model requests and write test proofs under the test build's ignored `bin/.../proofs` directory.

### Sentences continuing across pages

Page reviews receive the verified whole-document text comparison, the preceding page's final three narrative lines,
the next page's first three narrative lines, and explicit per-paragraph continuation flags. A sentence ending mid-page-turn
is normal pagination, not missing text. Full passages supplied as illustration context need not fit on that page.
The reviewer still checks visible clipping, overlap and unreadable text; exact text preservation remains a deterministic check.
This review-only change preserves the existing run fingerprint, layout and artwork caches. Only changed page-review requests
need fresh reviews; it does not request new illustrations or change the manuscript.
