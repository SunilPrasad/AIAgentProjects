using Microsoft.Agents.AI.Workflows;
using Microsoft.Agents.AI.Workflows.Checkpointing;
using Microsoft.Extensions.Logging;

namespace GreatIndians.Factory;

public sealed class BookFactory(BookConfig config, string style, string output, ModelGateway api, ILogger log)
{
    private readonly PromptSet prompts = new(config, style);
    private readonly string version = Data.Hash(
        Data.Write(config) + style + PromptSet.Version + typeof(BookFactory).Assembly.ManifestModule.ModuleVersionId);

    public async Task<int> RunAsync(CancellationToken ct)
    {
        var bookRoot = Path.Combine(output, Data.Slug(config.BookTitle) + "-" + Data.Hash(config.BookTitle)[..8]);
        var root = Path.Combine(bookRoot, "runs", version);
        Directory.CreateDirectory(root);
        await Data.SaveAsync(Path.Combine(bookRoot, "current-run.json"), Data.Write(new
        {
            directory = root,
            version,
            promptVersion = PromptSet.Version,
            chaptersDirectory = Path.Combine(output, "final-chapters"),
            updatedAt = DateTimeOffset.UtcNow
        }));
        var results = new List<ChapterResult>();
        var chapters = new List<object>();
        var bookCostMark = CostMeter.Mark();

        for (int index = 0; index < config.Personalities.Count; index++)
        {
            ct.ThrowIfCancellationRequested();
            var subject = config.Personalities[index];
            var name = config.ChapterName(index);
            var folder = Path.Combine(root, name);
            var previousFolders = Directory.EnumerateDirectories(Path.Combine(bookRoot, "runs"))
                .Where(previousRun => previousRun != root)
                .Select(previousRun => Path.Combine(previousRun, name))
                .Where(Directory.Exists)
                .OrderByDescending(Directory.GetLastWriteTimeUtc)
                .ToArray();
            var files = new Artifacts(folder, log, previousFolders);
            var chapterCostMark = CostMeter.Mark();
            var delivery = new ChapterDelivery(output, name, log, chapterCostMark);
            log.LogInformation("[{Chapter}][Orchestrator][START] Chapter {Index}/{Total}", subject, index + 1, config.Personalities.Count);
            ChapterResult result;

            try
            {
                result = await RunChapter(subject, files, delivery, ct);
            }
            catch (Exception exception)
            {
                var cause = FailureDetails.Unwrap(exception);

                if (cause is OperationCanceledException && ct.IsCancellationRequested)
                {
                    throw new OperationCanceledException(ct);
                }

                var reason = FailureDetails.Reason(cause);
                await files.Save("failure-details.json", FailureDetails.Report(exception));
                var draftPath = Path.Combine(folder, "chapter.md");
                var bestPath = Path.Combine(folder, "best-reviewed.json");
                ChapterCandidate? best = null;

                if (File.Exists(bestPath))
                {
                    try
                    {
                        best = Data.Read<ChapterCandidate>(await File.ReadAllTextAsync(bestPath, ct));
                    }
                    catch (System.Text.Json.JsonException)
                    {
                    }
                }

                if (best is not null || File.Exists(draftPath))
                {
                    var draft = best?.Draft ?? await File.ReadAllTextAsync(draftPath, ct);
                    result = await delivery.SaveAsync(
                        subject, draft, "CHAPTER_READY_REVIEW_INCOMPLETE",
                        $"A draft is available. A later stage failed: {reason}", files,
                        best?.Reviews, [new ReviewerFailure("Workflow", reason)], best?.Pass, finalGenerated: true);
                }
                else
                {
                    var status = cause is EditorialException ? "BLOCKED_RESEARCH" : "FAILED_BEFORE_DRAFT";
                    result = new ChapterResult(subject, status, folder, null, reason)
                    {
                        CostUsd = CostMeter.Since(chapterCostMark).TotalUsd
                    };
                    await files.Save("status.json", Data.Write(result));
                    await files.Save("research-notes.md", $"# {subject} — research status\n\n{reason}\n\nNo narrative draft was produced. Source evidence or model access must be resolved; no source material was invented.\n");
                }

                log.LogWarning("[{Chapter}][Orchestrator][{Status}] {Reason}", subject, result.Status, reason);
            }

            var chapterCost = CostMeter.Since(chapterCostMark);
            result = result with { CostUsd = chapterCost.TotalUsd };
            results.Add(result);
            await files.Save("cost.json", Data.Write(chapterCost));
            Console.WriteLine($"[{subject}] Chapter text cost: {chapterCost.OneLine()}");
            Console.WriteLine($"[BOOK] Running text cost: {CostMeter.Since(bookCostMark).Money()} after {index + 1}/{config.Personalities.Count} chapters");

            if (result.ChapterPath is not null)
            {
                chapters.Add(new
                {
                    subject,
                    status = result.Status,
                    chapter = await File.ReadAllTextAsync(Path.Combine(folder, "chapter.md"), ct)
                });
            }

            await BookArchive.SaveIndexAsync(output, config.BookTitle, results);
            await Data.SaveAsync(Path.Combine(root, "execution-summary.json"), Data.Write(new { chapters = results, complete = false }));
        }

        string bookStatus = "NO_DRAFTS_AVAILABLE";

        if (chapters.Count > 0)
        {
            try
            {
                var bookFiles = new Artifacts(Path.Combine(root, "book-review"), log);
                var report = await api.Agent(
                    "BOOK", "BookEditorialReviewer", "openrouter", config.ReviewerModel,
                    prompts.BookReview, Data.Write(new { title = config.BookTitle, chapters, chapterStatuses = results }),
                    bookFiles, "book-review", ct);
                var review = Data.Read<Review>(report);
                review.Validate();
                await bookFiles.Save("editorial-review.json", report);
                bookStatus = ReviewPolicy.PassesMandatoryChecks([review])
                    && results.All(result => result.Status == "AI_APPROVED_PENDING_HUMAN")
                        ? "AI_CHECKS_PASSED_PENDING_HUMAN"
                        : "DRAFT_BOOK_NEEDS_REVIEW";
            }
            catch (Exception exception)
            {
                if (FailureDetails.Unwrap(exception) is OperationCanceledException && ct.IsCancellationRequested)
                {
                    throw new OperationCanceledException(ct);
                }

                bookStatus = "DRAFT_BOOK_REVIEW_INCOMPLETE";
                await Data.SaveAsync(Path.Combine(root, "book-review", "failure-details.json"), FailureDetails.Report(exception));
                log.LogWarning("[BOOK][BookEditorialReviewer][INCOMPLETE] {Reason}; chapter drafts remain available", FailureDetails.Reason(exception));
            }
        }

        var bookCost = CostMeter.Since(bookCostMark);
        var drafted = results.Count(result => result.ChapterPath is not null);
        var approved = results.Count(result => result.Status == "AI_APPROVED_PENDING_HUMAN");
        await Data.SaveAsync(Path.Combine(root, "execution-summary.json"), Data.Write(new
        {
            book = config.BookTitle,
            complete = true,
            requested = results.Count,
            drafted,
            aiApproved = approved,
            draftsNeedingReview = drafted - approved,
            noDraft = results.Count - drafted,
            bookStatus,
            costUsd = bookCost.TotalUsd,
            cost = bookCost,
            publicationApproved = false,
            chaptersDirectory = Path.Combine(output, "final-chapters"),
            chapters = results
        }));
        log.LogInformation(
            "[BOOK][Orchestrator][COMPLETE] Requested={Requested}; drafts={Drafted}; AI-approved={Approved}; needs-review={NeedsReview}; no-draft={Missing}; chapters={Folder}",
            results.Count, drafted, approved, drafted - approved, results.Count - drafted, Path.Combine(output, "final-chapters"));
        Console.WriteLine($"[BOOK] Total text cost: {bookCost.OneLine()}");
        // Exit status reflects chapter production. Editorial approval remains explicit in the report.
        return drafted == results.Count ? 0 : 2;
    }

    private async Task<ChapterResult> RunChapter(
        string subject,
        Artifacts files,
        ChapterDelivery delivery,
        CancellationToken ct)
    {
        Directory.CreateDirectory(files.Root);
        var researcher = new Researcher(config, api, log);

        string WritingContext(ChapterState state) => Data.Write(new
        {
            subject,
            evidence = state.Ledger,
            references = state.Sources.Select(source => new { source.Id, source.Url, source.Title })
        });

        var research = new Stage("research", async (state, token) =>
        {
            var sources = await researcher.Gather(subject, files, token);
            var builder = new EvidenceBuilder(config, api, researcher, log, prompts.Rules);
            var ledger = await builder.BuildAsync(subject, sources, files, token);
            return state with { Sources = sources, Ledger = ledger };
        });
        var outline = new Stage("outline", async (state, token) =>
        {
            var text = await api.Agent(
                subject, "StoryPlanningAgent", "openrouter", config.WriterModel,
                prompts.Outline, WritingContext(state), files, "outline", token);
            await files.Save("outline.md", text);
            return state with { Outline = text };
        });
        var writer = new Stage("writer", async (state, token) =>
        {
            var text = await api.Agent(
                subject, "ChapterWritingAgent", "openrouter", config.WriterModel,
                prompts.Writer, WritingContext(state) + "\nOUTLINE:\n" + state.Outline,
                files, "draft-1", token);
            await files.Save("drafts/draft-1.md", text);
            await delivery.SaveAsync(
                subject, text, "DRAFT_REVIEW_PENDING", "First chapter draft is available; independent review is starting.", files);
            return state with { Draft = text };
        });
        var reviewers = new Stage("reviewers", async (state, token) =>
        {
            int pass = state.Pass + 1;
            var historyContext = Data.Write(new
            {
                subject,
                evidence = state.Ledger,
                citedSources = state.Sources.Where(source => state.Ledger!.Claims.Any(claim => claim.SourceId == source.Id))
            });
            var roles = new[]
            {
                (Name: "HistoricalReviewer", Model: config.ReviewerModel, Prompt: prompts.HistoricalReview, Context: historyContext),
                (Name: "ChildrensNarrativeReviewer", Model: config.WriterModel, Prompt: prompts.NarrativeReview, Context: ""),
                (Name: "CulturalSensitivityReviewer", Model: config.ReviewerModel, Prompt: prompts.CulturalReview, Context: "")
            };
            var outcomes = await Task.WhenAll(roles.Select(async role =>
            {
                try
                {
                    var report = await api.Agent(
                        subject, role.Name, "openrouter", role.Model, role.Prompt,
                        role.Context + "\nCHAPTER:\n" + state.Draft,
                        files, $"review-{pass}-{role.Name}", token);
                    var review = Data.Read<Review>(report);
                    review.Validate();
                    await files.Save($"reviews/pass-{pass}-{role.Name}.json", Data.Write(new
                    {
                        draftHash = Data.Hash(state.Draft),
                        role.Name,
                        role.Model,
                        review
                    }));
                    return new ReviewOutcome(role.Name, review, null);
                }
                catch (Exception exception)
                {
                    if (FailureDetails.Unwrap(exception) is OperationCanceledException && token.IsCancellationRequested)
                    {
                        throw new OperationCanceledException(token);
                    }

                    var failure = new ReviewerFailure(role.Name, FailureDetails.Reason(exception));
                    await files.Save($"reviews/pass-{pass}-{role.Name}-failure.json", FailureDetails.Report(exception));
                    log.LogWarning("[{Chapter}][{Agent}][UNAVAILABLE] {Reason}; preserving the chapter draft", subject, role.Name, failure.Reason);
                    return new ReviewOutcome(role.Name, null, failure);
                }
            }));
            var reviews = outcomes.Where(outcome => outcome.Review is not null).Select(outcome => outcome.Review!).ToList();
            var failures = outcomes.Where(outcome => outcome.Failure is not null).Select(outcome => outcome.Failure!).ToList();
            var audienceIssues = YoungReaderStyle.FindIssues(state.Draft);

            if (audienceIssues.Count > 0)
            {
                reviews.Add(new Review(false, audienceIssues,
                    "Young-reader style check: remove research commentary from the biography."));
            }

            var count = ReviewPolicy.WordCount(state.Draft);

            if (count < config.ChapterWordCountMin || count > config.ChapterWordCountMax)
            {
                reviews.Add(new Review(false,
                    [new Finding("CHAPTER", "major", $"Word count {count} outside {config.ChapterWordCountMin}-{config.ChapterWordCountMax}.",
                        $"Aim for {prompts.TargetWords} words; remove optional sections and repetition while retaining the main narrative.")],
                    "Deterministic word-count check needs correction."));
            }

            bool approved = failures.Count == 0 && outcomes.All(outcome => outcome.Review is not null)
                && ReviewPolicy.PassesMandatoryChecks(reviews);
            var candidate = new ChapterCandidate(state.Draft, pass, reviews, failures, count, approved);
            var candidates = (state.Candidates ?? []).Append(candidate).ToList();
            var best = ReviewPolicy.Best(candidates, config);
            await files.Save($"reviews/pass-{pass}-gate.json", Data.Write(new
            {
                draftHash = Data.Hash(state.Draft), wordCount = count, approved, reviews, failures
            }));
            await files.Save("best-reviewed.json", Data.Write(best));
            await delivery.SaveAsync(
                subject, best.Draft,
                failures.Count > 0 ? "DRAFT_REVIEW_INCOMPLETE" : best.Approved ? "AI_APPROVED_PENDING_HUMAN" : "DRAFT_NEEDS_REVIEW",
                best.Approved ? "Mandatory AI checks passed; minor notes may remain. Human approval is pending."
                    : "A readable chapter is available. See specific outstanding findings in its review report.",
                files, best.Reviews, best.Failures.Concat(failures).Distinct(), best.Pass);
            log.LogInformation(
                "[{Chapter}][QualityGate][REVIEW] Pass={Pass}; mandatory-approved={Approved}; findings={Findings}; reviewer-failures={Failures}; selected-pass={Selected}",
                subject, pass, approved, reviews.Sum(review => review.Findings.Count), failures.Count, best.Pass);
            return state with
            {
                Pass = pass, Reviews = reviews, ReviewFailures = failures,
                Candidates = candidates, Approved = approved
            };
        });
        var reviser = new Stage("reviser", async (state, token) =>
        {
            var basis = ReviewPolicy.Best(state.Candidates!, config);
            var text = await api.Agent(
                subject, "RevisionAgent", "openrouter", config.WriterModel, prompts.Reviser,
                WritingContext(state) + "\nCURRENT CHAPTER:\n" + basis.Draft + "\nREVISION PLAN:\n" + Data.Write(new
                {
                    currentWordCount = basis.WordCount,
                    targetWords = prompts.TargetWords,
                    minimum = config.ChapterWordCountMin,
                    maximum = config.ChapterWordCountMax,
                    findings = basis.Reviews
                }), files, $"draft-{state.Pass + 1}", token);
            await files.Save($"drafts/draft-{state.Pass + 1}.md", text);
            await files.Save($"revisions/revision-{state.Pass}.json", Data.Write(new
            {
                basedOnPass = basis.Pass,
                previousHash = Data.Hash(basis.Draft),
                revisedHash = Data.Hash(text),
                findings = basis.Reviews
            }));
            // The reviewed candidate remains available while its revision is awaiting review.
            return state with { Draft = text, Approved = false };
        });
        ChapterResult? finalResult = null;
        var finish = new Stage("finish", async (state, token) =>
        {
            researcher.Validate(state.Ledger ?? throw new InvalidDataException("Missing ledger."), state.Sources);
            var best = ReviewPolicy.Best(state.Candidates!, config);
            bool incomplete = best.Failures.Count > 0 || state.ReviewFailures is { Count: > 0 };
            var status = incomplete ? "CHAPTER_READY_REVIEW_INCOMPLETE"
                : best.Approved ? "AI_APPROVED_PENDING_HUMAN" : "CHAPTER_READY_NEEDS_REVIEW";
            var reason = best.Approved && !incomplete
                ? "Mandatory AI checks passed; optional minor notes are retained. Human publication approval is pending."
                : incomplete ? "Chapter draft delivered; one or more independent reviews could not complete."
                : "Chapter draft delivered after bounded improvement. Outstanding findings require human review.";


            finalResult = await delivery.SaveAsync(
                subject, best.Draft, status, reason, files, best.Reviews,
                best.Failures.Concat(state.ReviewFailures ?? []).Distinct(), best.Pass, finalGenerated: true);
            return state;
        });
        bool Finished(ChapterState? state) => state is not null
            && (state.Approved || state.Pass >= config.MaxReviewPasses || state.ReviewFailures is { Count: > 0 });
        var workflow = new WorkflowBuilder(research)
            .AddEdge(research, outline).AddEdge(outline, writer).AddEdge(writer, reviewers)
            .AddEdge<ChapterState>(reviewers, finish, Finished)
            .AddEdge<ChapterState>(reviewers, reviser, state => state is not null && !Finished(state))
            .AddEdge(reviser, reviewers).WithOutputFrom(finish).Build();
        using var checkpointStore = new FileSystemJsonCheckpointStore(new DirectoryInfo(Path.Combine(files.Root, "checkpoints")));
        var manager = CheckpointManager.CreateJson(checkpointStore, Data.Json);
        // Resume checkpoints only while all retained artifacts still match the saved manifest.
        // Otherwise re-enter the graph; hashed stage caches avoid repeated successful model calls.
        string Fingerprint() => Data.Hash(string.Join("\n", Directory.EnumerateFiles(files.Root, "*", SearchOption.AllDirectories)
            .Where(p => !Path.GetRelativePath(files.Root, p).StartsWith("checkpoints" + Path.DirectorySeparatorChar)
                && !p.EndsWith("workflow-session.json") && !p.EndsWith("status.json") && !Path.GetFileName(p).Contains(".tmp-"))
            .OrderBy(p => p).Select(p => Path.GetRelativePath(files.Root, p) + ":" + Data.Hash(File.ReadAllText(p)))));
        var sessionPath = Path.Combine(files.Root, "workflow-session.json");
        WorkflowSession? saved = null;
        if (File.Exists(sessionPath))
        {
            try
            {
                saved = Data.Read<WorkflowSession>(await File.ReadAllTextAsync(sessionPath, ct));
            }
            catch (System.Text.Json.JsonException)
            {
            }
        }
        bool generationFinished = false;
        var statusPath = Path.Combine(files.Root, "status.json");
        if (File.Exists(statusPath))
        {
            try
            {
                generationFinished = Data.Read<ChapterResult>(await File.ReadAllTextAsync(statusPath, ct)).IsFinalGenerated;
            }
            catch (System.Text.Json.JsonException)
            {
                generationFinished = true; // Rebuild from validated caches if status metadata is corrupt.
            }
        }
        bool canResume = saved is not null && saved.Fingerprint == Fingerprint() && !generationFinished;
        string sessionId = canResume ? saved!.SessionId : Guid.NewGuid().ToString("N");
        foreach (var stage in new[] { research, outline, writer, reviewers, reviser, finish })
        {
            stage.After = () => files.Save("workflow-session.json", Data.Write(new WorkflowSession(sessionId, Fingerprint())));
        }

        var checkpoint = canResume ? await manager.GetLatestCheckpointAsync(sessionId, ct) : null;
        if (checkpoint is not null)
        {
            log.LogInformation("[{Chapter}][Orchestrator][RESUME] Restoring MAF checkpoint", subject);
        }

        var run = checkpoint is not null
            ? await InProcessExecution.ResumeAsync(workflow, checkpoint, manager, ct)
            : await InProcessExecution.RunAsync(workflow, new ChapterState(subject, []), manager, sessionId, ct);
        var failure = run.OutgoingEvents.OfType<WorkflowErrorEvent>().FirstOrDefault();
        if (failure is not null)
        {
            throw failure.Exception ?? new InvalidOperationException("Workflow failed.");
        }

        return finalResult ?? throw new InvalidOperationException("Workflow ended without a final quality gate result.");
    }
    private sealed record WorkflowSession(string SessionId, string Fingerprint);
    private sealed class Stage(string id, Func<ChapterState, CancellationToken, Task<ChapterState>> action) : Executor<ChapterState, ChapterState>(id)
    {
        public Func<Task>? After
        {
            get; set;
        }
        public override async ValueTask<ChapterState> HandleAsync(ChapterState message, IWorkflowContext context, CancellationToken cancellationToken = default)
        {
            var result = await action(message, cancellationToken);
            if (After is not null)
            {
                await After();
            }

            return result;
        }
    }
}
