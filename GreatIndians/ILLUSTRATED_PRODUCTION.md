# Illustrated chapter production

This is a separate production command for the existing researched Markdown chapters. It never runs the research/writing pipeline and never asks a model to rewrite the manuscript. The supplied [master requirements](PRODUCTION_REQUIREMENTS.md) are retained in full. PDF chapter production is implemented here; reflowable EPUB generation is included by default, with Kindle preview explicitly still required. Full-book assembly and cover/spine production remain separate work.

## Run one chapter

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

1. Parse the saved manuscript into paragraphs with stable IDs and preserve inline italics/bold. Retain an unchanged Markdown snapshot and source SHA-256. Suppress secondary headings only in the layout and list them in QA; reject unsupported markup rather than silently losing content.
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
- Artwork: `google/gemini-3-pro-image`, 2K.
- Image and rendered-page review: `anthropic/claude-sonnet-4.5`.

The image adapter uses OpenRouter's [dedicated image API](https://openrouter.ai/docs/guides/overview/multimodal/image-generation). Planning/review use structured JSON responses. Provider availability and costs can vary. A four-illustration chapter requires four image generations, four image reviews, a planning call, and one vision call per PDF page; retries add calls. The approved opening image doubles as its character reference, removing one generation and one review (20% fewer base image-generation calls). Google Pro remains the default. Usage returned by OpenRouter is logged. `--inspect` makes no API calls.

Set `bookPageCountForGutter` to the anticipated **whole book** page count when known. Zero uses approximately 0.76-inch side margins matching the reference text column, but the assembled book still needs its actual gutter checked. Standalone chapters do not establish KDP minimum book length, cover/spine dimensions, full-book pagination, colour/print-profile suitability or physical proof quality. No scientific diagrams are generated by AI; existing formulas remain selectable text, and any future added scientific diagram needs deterministic construction and its own validation.

The renderer is pinned to PDFsharp 6.2.4 (MIT); newer 6.5 releases change licensing. Bundled Liberation Serif font terms are in `GreatIndians.Factory/assets/fonts/Liberation-LICENSE.txt`. PDF rendering uses PDFium/SkiaSharp native assets restored by NuGet; Windows x64 is the verified development platform.

Matching stage results can be reused across earlier run folders for the same chapter only when their complete input/output hashes agree, including model, source, full prompts and all reference-image hashes. A line-spacing-only configuration change can reuse artwork while rendering and reviewing the changed PDF afresh. A changed visual style requires new art; previous approved output stays in its original folder.

## Design authority

ProductionDesign.cs is the shared definition used for print layout, EPUB CSS and page-review instructions. Each run records its version and settings in design.json. The command logs the applied font, size, leading and paper colour before paid calls. --inspect also shows the design without API calls. Body font size is fixed at 12.1pt; configuration is rejected if it would shrink the text or move leading outside 16.5–17.5pt. The written master controls typography, safety and the palette. The supplied art reference controls the intended saturation, golden lighting, dimensional painted detail and atmospheric finish.

### Reference matching and balanced pages (reference-balanced-v4)

The planner locks one adult appearance, including facial hair, hairstyle and clothing colours. Every later image is generated and reviewed against the approved opening character. Review responses must include specific character and style comparisons, plus passing checks for reference colour/lighting, painterly detail and character features. A generic storybook resemblance or a clean-shaven-to-bearded substitution is insufficient. Rejected scenes alone are retried within the configured limit; actual model judgements still need the author's final visual approval.

Before paid page reviews, the renderer compares four local layouts. It can modestly resize complete illustrations at their existing narrative anchors, uses 8pt paragraph gaps and a 54pt continuation-page top margin, and scores page count and excess whitespace. It never crops images, changes manuscript order, shrinks text or changes configured leading. A nearly empty final continuation page (fewer than six body lines, without artwork) fails deterministic checks and triggers the remaining layout attempt before finalisation. Only the selected proof is sent for vision review, so local comparisons add no API calls.

The new prompt/design versions create a separate run folder. Older artwork reviews do not meet the new required review fields; changed image prompts require new artwork. Existing story files and previous output folders remain intact. Run `dotnet run -- pdf --chapter Baudhayana` from `GreatIndians.Factory` as usual.

## Verification performed

Offline layout checks used all ten current manuscripts and geometric placeholder images: source paragraph order and text matched PDF/EPUB, fonts were embedded, images exceeded 300 PPI, and all PDF pages rendered. An injected offline HTTP handler exercises planning, image generation/review and page-review wiring, including refusal to finalise cropped images. These fixtures are not historical illustrations or evidence of real vision-model accuracy. Live paid generation and review are left for the user's run.

Run the committed native layout and review-gate regression checks from the repository root:

```powershell
dotnet run --project GreatIndians/tests/Production.RegressionTests
```

The tests use geometric placeholders and generated text fixtures, verify exact PDF/EPUB text and aspect ratios, check illustration anchors and sparse-page rejection, and reject missing character/style review evidence. Pass a directory containing ten retained Markdown chapters after `--` to exercise those manuscripts instead. They make no model requests and write test proofs under the test build's ignored `bin/.../proofs` directory.
