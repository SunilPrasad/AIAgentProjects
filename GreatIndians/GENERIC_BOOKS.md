# Reusable book definitions and real web photographs

The writing and illustration commands can now share one book definition. Existing `book.json`, `production.json`, `dotnet run` and `dotnet run -- pdf ...` commands remain supported. Existing manuscript/output folders are not migrated or overwritten by selecting a new book definition.

## The four configured collections

| Definition | Content profile | Default image policy |
|---|---|---|
| `books/ancient-india.json` | Biography | Generated illustrations |
| `books/modern-india.json` | Biography | Prefer suitable real photographs; otherwise generate |
| `books/indian-science.json` | Scientific biography | Prefer suitable real photographs; otherwise generate |
| `books/sacred-temples.json` | Temple | Prefer suitable real photographs; otherwise generate |

All forty requested subjects are included, in the requested chapter order. Each has a stable ID, display name, optional aliases, an image-search query and an optional curated Commons file list. Chapter numbering is the order in the definition. Output is isolated under `output/books/<book-id>/`; caches cannot accidentally cross book roots.

## Run a book

From `GreatIndians/GreatIndians.Factory`:

```powershell
# Verify configuration and chapter IDs without model calls
dotnet run -- --book ../books/modern-india.json --inspect

# Research, write and independently review the ten configured chapters
dotnet run -- --book ../books/modern-india.json

# Illustrate an existing manuscript by stable ID, name or configured alias
dotnet run -- pdf --book ../books/modern-india.json --chapter mahatma-gandhi

# Illustrate all retained manuscripts for that book
dotnet run -- pdf --book ../books/modern-india.json --all

# Inspect production inputs without model calls
dotnet run -- pdf --book ../books/modern-india.json --all --inspect
```

Substitute `indian-science.json` or `sacred-temples.json` for the other collections. The Ancient India definition starts a separate new collection under `output/books/ancient-india`; it does not silently import the previously generated Ancient India files. Use your existing commands/config to continue that original run.

New shared books require matching completed mandatory editorial checks before illustration. Status is bound to the current manuscript text hash. `AI_APPROVED_PENDING_HUMAN` permits production; human publication approval is still separate. If you deliberately need an unresolved draft proof, use:

```powershell
dotnet run -- pdf --book ../books/modern-india.json --chapter mahatma-gandhi --allow-unreviewed
```

This override permits a proof, not editorial approval. Image, source-integrity, PDF text and page checks are still mandatory. Legacy configurations retain their previous editorial hand-off behaviour.

## Define another topic

Supported profiles: `biography`, `scientific-biography`, `temple`, `place`, `event`, `nonfiction`. A book may have any positive number of subjects; there is no ten-subject requirement. A generic topic can be one subject/chapter, or several explicitly configured subjects/chapters. To research and select a chapter list from a title, run the separate [three-juror discovery command](TOPIC_DISCOVERY.md) first. Each selected topic requires two of three votes; successful discovery updates the shared JSON automatically and preserves the downstream review requirements.

```json
{
  "schemaVersion": 1,
  "id": "remarkable-rivers",
  "title": "Remarkable Rivers",
  "subtitle": "Illustrated nonfiction for curious young readers",
  "author": "Sunil Bhardwaj",
  "profile": "place",
  "audienceMinAge": 8,
  "audienceMaxAge": 12,
  "language": "British English",
  "outputRoot": "../output/books",
  "requireEditorialApproval": true,
  "subjects": [
    {
      "id": "river-ganga",
      "name": "River Ganga",
      "aliases": ["The Ganges"],
      "imageQuery": "Ganges river landscape",
      "commonsFiles": []
    }
  ],
  "writing": {
    "chapterWordCountMin": 600,
    "chapterWordCountMax": 900
  },
  "production": {
    "imageMode": "preferWeb",
    "maxWebCandidates": 3,
    "illustrationCount": 4,
    "minimumImageScore": 70,
    "maxImageAttempts": 3,
    "createEpub": true
  }
}
```

Paths in a definition resolve relative to the definition file. Omitted style settings use bundled common reader/art profiles. Explicit custom style paths must exist. Book/subject IDs use lowercase letters/digits and hyphens. Duplicate names/aliases are rejected. Canonical chapter filenames such as `01-river-ganga.md` identify the subject even if the creative headline omits its name; title/alias matching remains available for other filenames.

`SubjectDefinition`, `BookDefinition` and `ContentProfiles` hold shared metadata. The serialized illustration-plan field named `character` remains for backward compatibility: for a place or temple it represents the visual subject's structural appearance/environment, with human-only fields marked not applicable. A person portrait is not required for those profiles.

## Real-image policies

| `production.imageMode` | Behaviour |
|---|---|
| `generated` | Existing generated-art path; no Commons image search |
| `preferWeb` | Search, filter, download and review a bounded set of real images; use generation only if none passes |
| `webOnly` | Use only suitable reviewed real images; stop if none passes, without purchasing generated artwork |

Automated web sourcing is deliberately limited to Wikimedia Commons PNG/JPEG originals and Commons-reported reusable license metadata. This is not unrestricted image scraping or Google Images downloading.

Before scene planning, production now tries a plain name without honorifics, the configured subject name, aliases and the optional image query (at most six distinct queries). It also resolves images embedded in likely English Wikipedia articles to their original Commons file metadata. No extra `scientist portrait` terms or forced `filetype:bitmap` suffix are added to plain-name searches. Curated `commonsFiles` are checked first and combined with discovered candidates. Candidates are deduplicated by original URL; metadata searches refresh daily, including empty results, and old narrow-query empty caches cannot block alternatives. Each query/failure and the resulting candidate list are recorded in `provenance/commons-candidates.json`.

The planner receives a bounded inventory of available photos before describing scenes. It should use portraits for introductions, real apparatus for corresponding research, and appropriate site/institute photographs for related passages. Photo reviewers assess the actual manuscript passage rather than requiring the exact composition of an imagined generated scene. Candidates are ranked for passage relevance before applying `maxWebCandidates`, which still bounds paid image reviews per scene. Documentary identity, authenticity, source/license metadata, resolution and PDF checks remain mandatory. `preferWeb` generates only if no reviewed candidate passes; `webOnly` never purchases generated images and stops before planning if discovery finds no candidates.

The importer requires an explicit Creative Commons license URL for CC BY, CC BY-SA, CC0 or Public Domain Mark, with a named creator. It rejects unsupported/missing metadata, noncommercial/no-derivatives/fair-use labels, restriction notices, unsupported formats, unsafe hosts, undersized images and extreme dimensions. Some public-domain files lack this metadata and will be skipped; the tool does not guess their rights. Commons metadata is evidence, not a legal guarantee: inspect the original file page and applicable terms before publication.

Set `imageQuery` to disambiguate a site/person. For example, the Jagannath query explicitly names Puri, and the Venkateswara query names Tirumala. Search results are candidates, not proof of identity. To prioritise known real files in the candidate inventory, provide their exact Commons titles:

```json
{
  "id": "your-subject",
  "name": "Your subject",
  "imageQuery": "Your subject and location",
  "commonsFiles": ["File:Exact existing filename on Commons.jpg"]
}
```

The example filename is a placeholder, not an asserted source. For a real configuration, copy the title from the original Commons file page. Do not add a normal webpage URL or a raw arbitrary image URL to this list.

### Review and consistency

- Both generated and real assets must pass the configured weighted score and all mandatory visual/subject/passages checks.
- Source candidates have an additional real-photograph/authenticity assessment; drawings, AI renders, screenshots and reconstructions do not qualify. Metadata explicitly indicating AI generation is filtered before download. This is a model assessment, not a forensic guarantee.
- Real-photo style is evaluated as a photograph, without forcing watercolour texture or fictional clothing colours.
- Authentic incidental inscriptions can remain. Added/generated captions and watermarks cannot.
- A contemporary temple photograph must not be presented as documentary evidence of an ancient construction event or lost historical appearance.
- Photographs retain their aspect ratios and are proportionally contained. The generated scene's requested aspect ratio is not used to crop a real photo.
- The first accepted image supplies the subsequent visual reference, meaning a person's identity or a temple/place's distinctive structure. The same downloaded image is not accepted twice within a chapter.
- The scored compromise policy remains: default overall 70/100, every category at least 50, with hard defects unable to be averaged away. Candidate review is paid even when its source download is free; `maxWebCandidates` bounds candidates per scene.

### Attribution and provenance

Accepted real images carry creator, title, source/file-page URL, original download URL, reported license/link, credit line and original byte hash. Source metadata and download receipts are saved in provenance/cache. Existing download results and reviews can be reused when complete inputs/output hashes match.

Image credits are added to separate PDF pages and an EPUB credit section, not to the researched narrative. Exact source-paragraph comparison excludes only those designated credit pages while still validating complete page text and safe placement. Credit pages are rendered and reviewed like other pages. Additional sidecars are `image-credits.md`, `image-credits.json` and the per-image manifest's `sourceKind`/`Credit` fields. Whole-book assembly preserves the credit pages.

The manuscript is never rewritten by image production. Research still requires accessible sources and exact excerpt binding, with historical/factual, narrative and cultural reviews, word-count/style checks and bounded revisions. Temple profiles add respectful belief attribution and architecture checks; scientific biographies add discovery attribution, collaborators and scientific accuracy. Unsupported claims are omitted rather than invented.

## Whole-book assembly without hardcoded Ancient India settings

The new repository tools read the same book definition. Existing one-off workspace scripts are preserved.

Install their dependencies in your chosen Python environment once, if needed:

```powershell
python -m pip install -r tools/requirements.txt
```

From the `GreatIndians` directory:

```powershell
# Inspect planned paths before assembly
python tools/assemble_book.py --book books/modern-india.json --inspect

# Assemble all configured, approved illustrated chapters (no model calls)
python tools/assemble_book.py --book books/modern-india.json

# Include a supplied front cover and prepare a cover-spread REVIEW proof
python tools/assemble_book.py --book books/modern-india.json --cover "C:/path/to/front-cover.png"

# Make a reader PDF with the supplied cover if one was assembled
python tools/prepare_reader.py --book books/modern-india.json
```

Assembly verifies approved PDF hashes, retained manuscript hashes and the matching layout manifests, adds title/contents and continuous numbering, preserves source text and credit pages, corrects mirrored page parity and adds bleed. Page count is derived, not fixed to 50. Output goes to `output/books/<id>/assembled`; reader output goes to `output/books/<id>/sales/etsy` with a 20 MB file-size check. `coverImage` (relative path) and `backCoverText` may optionally be supplied in the shared JSON for the Python assembler; no cover is generated automatically.

Print files are review proofs: publication still needs a human check of all text, licenses, physical print/cover quality and the relevant marketplace requirements. These commands do not upload or publish anything, do not create new covers and do not certify print acceptance. Whole-book EPUB assembly is not included; the C# workflow produces per-chapter EPUBs.

## Verification and limits

Run `dotnet run --project tests/Production.RegressionTests` from `GreatIndians`.

Offline tests cover all four manifests, arbitrary subject counts, filename IDs/aliases, invalid IDs, profile prompts, editorial hand-off, license/URL filtering, a complete web-only photo workflow, PDF/EPUB credits, exact text preservation, cache-only reruns, web-only failure and generated fallback. Existing page-continuation, score, native layout and manuscript checks remain covered. Fake HTTP handlers exercise calls without contacting a provider; they do not prove real search availability or live vision-model accuracy.

Writing research currently extracts HTML/text, not PDF source documents. There is no exhaustive historical truth guarantee or unbounded budget promise; source/review failures remain explicit. Web search, image reviews and fallback generations depend on available external services when the user runs them.

Implementation references: [MediaWiki Imageinfo API](https://www.mediawiki.org/wiki/API:Imageinfo), [Wikimedia content reuse](https://www.mediawiki.org/wiki/Wikimedia_APIs/Content_reuse), [Creative Commons reuse guidance](https://creativecommons.org/reusing-cc-licensed-content/).
