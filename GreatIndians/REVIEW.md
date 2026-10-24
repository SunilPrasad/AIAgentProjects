# Review of the original prototype

Reviewed against the supplied Fully Autonomous Book Writing Pipeline requirements.
The implementation originally pushed in commit 214e98b was a single-chapter drafting prototype.
It already used direct OpenAI and Anthropic API calls; Azure AI Foundry was never required.

## Findings

1. **Build blocker:** Microsoft.Agents.AI.OpenAI 1.25.0 requires OpenAI >= 2.14.0, but the project
   pinned 2.8.0. Confirmed by a real failed restore/build (NU1605). Updated to 2.14.0.
2. **Wrong entry workflow:** plain `dotnet run` only printed usage. It required a manually prepared,
   human-approved evidence file and could process only one chapter per invocation.
3. **No research:** checking that source and quote strings were nonempty did not verify source
   existence, excerpt provenance or claim support. The source template intentionally had placeholders.
4. **Incomplete orchestration:** agents were real MAF agents, but a hand-written C# loop controlled
   the workflow. There were no MAF workflow dependencies, conditional edges or checkpoints.
5. **Incomplete review contract:** only one broad Claude reviewer existed. Required JSON properties
   and null collections were not validated explicitly. A missing/null findings collection could crash.
6. **No recovery or failure isolation:** timestamps created new output folders, successful stages
   could not be reused, and API errors terminated execution without a durable failure summary.
7. **Missing book stages:** no permanent Style Bible, book/personality configuration, narrative
   outline, specialised review agents or book-wide consistency review.
8. **Wrong phase scope:** the art-director agent generated illustration briefs after approval,
   contrary to the new text-only requirements.
9. **Insufficient observability:** no stage-level live logging, usage/provenance records, retry policy,
   explicit technical-failure status or final book execution summary.

The replacement adds these architectural stages and safeguards; see README.md for the execution
flow, outputs, remaining limits and validation performed. Live integrations have NOT been tested.
