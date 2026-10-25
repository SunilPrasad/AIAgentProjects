# Whole-pipeline review and redesign

The user's last live run successfully researched, created an exact-source ledger, wrote three
chapters and obtained reviews. The failure to deliver was architectural: the application treated
unanimous reviewer approval as a prerequisite to exposing the chapter.

## Problems found

- A finished 1,051-word chapter remained buried under a hashed run path because there was no
  approved `final.md`. Draft creation and publication readiness were conflated.
- Shared prompts applied a chapter word target to non-writing agents. Source data was repeated
  in every role, increasing cost without clear benefit.
- Reviewers overlapped and gave conflicting instructions. One wanted a more explicit imagined
  opening while another wanted it shorter. A cautious zero statement was labelled critical for
  preferring a different wording. The main geocentrism issue had a simpler solution: omit the
  nonessential disputed paragraph rather than expand its qualifications.
- Revisions pursued every note and grew beyond the word limit. There was no regression control:
  the latest draft always displaced the previous one even when reviews worsened.
- One failed reviewer or reviser could stop delivery despite an existing usable chapter.
- Any code change isolated successful model calls in a new run namespace, wasting reusable work.

## Revised approach

Chapter generation is the product. Evidence provenance remains a prerequisite; independent review
improves and labels the result rather than hiding it. A selected final generated chapter is always
saved after the bounded writing/review process, with editorial/technical issues in separate files.
Human publication approval remains false. Lack of source evidence or failure before writing still
has an explicit unavailable result; no fabricated fallback is used.

Prompts are centralised in `PromptSet.cs`: a curiosity-led opening, one narrative thread, concrete
modern explanatory examples and a short closing note. No invented childhood scenes are required.
The target is the middle of the configured range. Reviews have narrow roles and a common severity
rubric. Minor preferences are advisory. Revisions prioritise concrete substantive issues and actual
word count, preserve good passages and remove weak optional assertions instead of expanding them.

Every reviewed candidate is retained. Selection favours mandatory-check approval, completed review,
fewer critical/major issues, compliant length and fewer minor notes. Revisions start from the best
reviewed candidate. This is a pragmatic selection rule, not proof of literary quality; the narrative
review and human editor still assess engagement.

Reader-facing chapters appear under `output/chapters`, with a report and status sidecar. The archive
keeps clean `final.md` alongside full provenance regardless of outstanding editorial findings. A
`--export-existing` mode recovers earlier work without API calls. All produced chapters participate
in book-wide review. API outages remain technical failures and do not become invented rejections.

Exact-input successful caches can survive version changes; prompt/content changes invalidate their
calls. Framework checkpoints and approval metadata are never transferred across versions. All reused
review content is bound again to the same draft. The user's one-personality configuration is kept.

## Evidence of validation

The build passes. Seven full offline workflow scenarios verified actual MAF orchestration and final
file delivery through unresolved findings, reviewer outages, revision failures and length correction.
A worsening revision retained the earlier better candidate; minor-only notes did not cause churn.
Archive export made no transport calls and did not alter original approval records. No new paid model
calls were made. The included 776-word Aryabhata example is explicitly a Codex-authored editorial
example using retained evidence, not a claimed live application result or an independent approval.

## Subsequent editorial direction

The user requested a biography-first style. Prompt version `biography-first-v3` supersedes the
question-led opening and closing History Detective note described in the initial redesign. Open
with the person, keep explanations within their documented life/work, omit unknown personal details
instead of discussing missing records, and end with legacy. Source qualifications remain in the
review report unless essential to a claim that must appear in the chapter. The example has been
rewritten as a 741-word biography, with no invented birthplace or childhood events.

## Young-reader emphasis

Prompt version `young-reader-biography-v4` makes the child audience explicit in every role. The
writer/reviser omit paragraphs about legends, missing records or scholarly uncertainty; disputed
details are omitted or briefly attributed only when essential, never turned into invented facts.
The narrative reviewer checks this preference. A focused deterministic style check also sends
recognisable research-disclaimer wording back for revision without suppressing final delivery.
The quoted Chanakya paragraph, simple biography and brief attribution were checked offline.
