using System.Text;
using Microsoft.Extensions.Logging;

namespace GreatIndians.Factory;

public sealed class ChapterDelivery(string outputDirectory, string chapterName, ILogger log, CostMeter.Position? costMark = null)
{
    public async Task<ChapterResult> SaveAsync(
        string subject,
        string draft,
        string status,
        string reason,
        Artifacts files,
        IEnumerable<Review>? reviews = null,
        IEnumerable<ReviewerFailure>? failures = null,
        int? selectedPass = null,
        bool updateArchive = true,
        bool finalGenerated = false)
    {
        var destination = Path.Combine(outputDirectory, "chapters");
        var chapterDirectory = finalGenerated
            ? Path.Combine(outputDirectory, "final-chapters")
            : destination;
        var chapterPath = Path.Combine(chapterDirectory, chapterName + ".md");
        var reviewPath = Path.Combine(destination, chapterName + "-review.md");
        var result = new ChapterResult(
            subject, status, files.Root, Data.Hash(draft), reason,
            chapterPath, reviewPath, selectedPass, finalGenerated)
        {
            CostUsd = costMark is null ? null : CostMeter.Since(costMark).TotalUsd
        };

        // The chapter remains clean reading text; review/approval metadata lives alongside it.
        if (updateArchive)
        {
            await files.Save("chapter.md", draft);
            await files.Save("status.json", Data.Write(result));

            if (finalGenerated)
            {
                await files.Save("final.md", draft);
            }
        }

        await Data.SaveAsync(chapterPath, draft);

        if (finalGenerated)
        {
            var interimPath = Path.Combine(destination, chapterName + ".md");
            if (File.Exists(interimPath) && Data.Hash(await File.ReadAllTextAsync(interimPath)) == result.ContentHash)
            {
                File.Delete(interimPath);
            }
        }

        var report = new StringBuilder();
        report.AppendLine($"# {subject} — chapter review");
        report.AppendLine();
        report.AppendLine($"- Status: **{status}**");
        report.AppendLine($"- {reason}");
        report.AppendLine($"- Word count: {ReviewPolicy.WordCount(draft)}");
        report.AppendLine($"- Selected review pass: {selectedPass?.ToString() ?? "not yet reviewed"}");
        report.AppendLine($"- Draft SHA-256: `{result.ContentHash}`");
        report.AppendLine($"- Run artifacts: {files.Root}");
        if (result.CostUsd is { } cost)
        {
            report.AppendLine($"- Model cost for this chapter in this run: {CostSummary.Format(cost)} (cached stages are free)");
        }
        report.AppendLine("- Human publication approval: **pending**");
        report.AppendLine();

        foreach (var failure in failures ?? [])
        {
            report.AppendLine($"## Review unavailable: {failure.Agent}");
            report.AppendLine(failure.Reason);
            report.AppendLine();
        }

        var reports = reviews?.ToList() ?? [];

        if (reports.Count == 0)
        {
            report.AppendLine("Independent reviews have not completed. Draft availability does not imply approval.");
        }

        foreach (var review in reports)
        {
            report.AppendLine("## Review findings");
            report.AppendLine(review.Summary);
            report.AppendLine();

            foreach (var finding in review.Findings)
            {
                report.AppendLine($"### {finding.Severity.ToUpperInvariant()} — {finding.ClaimId}");
                report.AppendLine(finding.Issue);
                report.AppendLine();
                report.AppendLine($"Suggested correction: {finding.RecommendedFix}");
                report.AppendLine();
            }
        }

        if (updateArchive)
        {
            await files.Save("review-notes.md", report.ToString());
        }
        await Data.SaveAsync(reviewPath, report.ToString());
        await Data.SaveAsync(Path.Combine(destination, chapterName + ".status.json"), Data.Write(result));
        log.LogInformation(
            "[{Chapter}][Delivery][SAVED] {Status}; chapter={ChapterPath}; review={ReviewPath}",
            subject, status, chapterPath, reviewPath);

        return result;
    }
}

public static class BookArchive
{
    public static async Task<int> ExportExistingAsync(
        BookConfig config,
        string outputDirectory,
        ILogger log,
        CancellationToken ct)
    {
        var bookRoot = Path.Combine(
            outputDirectory, Data.Slug(config.BookTitle) + "-" + Data.Hash(config.BookTitle)[..8]);
        var runsRoot = Path.Combine(bookRoot, "runs");

        if (!Directory.Exists(runsRoot))
        {
            log.LogWarning("[BOOK][Delivery][EMPTY] No previous run artifacts exist.");
            return 2;
        }

        int exported = 0;
        var results = new List<ChapterResult>();

        for (int index = 0; index < config.Personalities.Count; index++)
        {
            ct.ThrowIfCancellationRequested();
            var subject = config.Personalities[index];
            var name = config.ChapterName(index);

            foreach (var run in Directory.EnumerateDirectories(runsRoot).OrderByDescending(Directory.GetLastWriteTimeUtc))
            {
                var chapterRoot = Path.Combine(run, name);
                var draftsRoot = Path.Combine(chapterRoot, "drafts");

                if (!Directory.Exists(draftsRoot))
                {
                    continue;
                }

                var candidates = new List<ChapterCandidate>();

                foreach (var draftPath in Directory.EnumerateFiles(draftsRoot, "draft-*.md"))
                {
                    var number = Path.GetFileNameWithoutExtension(draftPath)["draft-".Length..];

                    if (!int.TryParse(number, out var pass))
                    {
                        continue;
                    }

                    var draft = await File.ReadAllTextAsync(draftPath, ct);
                    var gatePath = Path.Combine(chapterRoot, "reviews", $"pass-{pass}-gate.json");
                    List<Review> reviews = [];
                    List<ReviewerFailure> failures = [new("Archive", "No matching complete review gate was found for this draft.")];

                    if (File.Exists(gatePath))
                    {
                        try
                        {
                            using var gate = System.Text.Json.JsonDocument.Parse(await File.ReadAllTextAsync(gatePath, ct));
                            var root = gate.RootElement;

                            if (root.GetProperty("draftHash").GetString() == Data.Hash(draft))
                            {
                                reviews = Data.Read<List<Review>>(root.GetProperty("reviews").GetRawText());
                                foreach (var review in reviews)
                                {
                                    review.Validate();
                                }
                                failures = root.TryGetProperty("failures", out var savedFailures)
                                    ? Data.Read<List<ReviewerFailure>>(savedFailures.GetRawText())
                                    : [];
                            }
                        }
                        catch (Exception exception) when (exception is System.Text.Json.JsonException or InvalidDataException or KeyNotFoundException)
                        {
                            reviews = [];
                            failures = [new("Archive", "Saved review gate is incomplete or invalid; approval was not imported.")];
                        }
                    }

                    candidates.Add(new ChapterCandidate(
                        draft, pass, reviews, failures, ReviewPolicy.WordCount(draft), false));
                }

                if (candidates.Count == 0)
                {
                    continue;
                }

                var selected = ReviewPolicy.Best(candidates, config);
                var delivery = new ChapterDelivery(outputDirectory, name, log);
                var result = await delivery.SaveAsync(
                    subject, selected.Draft, "DRAFT_RECOVERED_NEEDS_REVIEW",
                    "Recovered an existing chapter without model calls. Earlier approval was not transferred; review the attached findings.",
                    new Artifacts(chapterRoot, log), selected.Reviews, selected.Failures, selected.Pass, updateArchive: false, finalGenerated: true);
                results.Add(result);
                exported++;
                break;
            }
        }

        await SaveIndexAsync(outputDirectory, config.BookTitle, results);
        log.LogInformation("[BOOK][Delivery][COMPLETE] Exported {Count} existing chapters without API calls; folder={Folder}", exported, Path.Combine(outputDirectory, "final-chapters"));
        return exported == config.Personalities.Count ? 0 : 2;
    }

    public static Task SaveIndexAsync(string outputDirectory, string bookTitle, IEnumerable<ChapterResult> results)
    {
        var text = new StringBuilder($"# {bookTitle}\n\nGenerated chapter drafts. Human publication approval remains pending.\n\n");

        foreach (var result in results)
        {
            if (result.ChapterPath is not null)
            {
                var chapterLink = Path.GetRelativePath(outputDirectory, result.ChapterPath).Replace('\\', '/');
                var reviewLink = Path.GetRelativePath(outputDirectory, result.ReviewPath!).Replace('\\', '/');
                text.AppendLine($"- [{result.Subject}]({chapterLink}) — {result.Status}; [review]({reviewLink})");
            }
            else
            {
                text.AppendLine($"- {result.Subject} — {result.Status}: {result.Reason}");
            }
        }

        return Data.SaveAsync(Path.Combine(outputDirectory, "index.md"), text.ToString());
    }
}
