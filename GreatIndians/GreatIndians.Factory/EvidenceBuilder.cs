using Microsoft.Extensions.Logging;

namespace GreatIndians.Factory;

public sealed record EvidenceExcerpt(string Id, string SourceId, int Start, int Length, string Quote);
public sealed record SelectedClaim(
    [property: System.Text.Json.Serialization.JsonRequired] string Id,
    [property: System.Text.Json.Serialization.JsonRequired] string Text,
    [property: System.Text.Json.Serialization.JsonRequired] string ExcerptId);
public sealed record LedgerSelection(
    [property: System.Text.Json.Serialization.JsonRequired] List<SelectedClaim> Claims);

public sealed class EvidenceBuilder(
    BookConfig config,
    ModelGateway api,
    Researcher researcher,
    ILogger log,
    string commonInstructions)
{
    public async Task<Evidence> BuildAsync(
        string subject,
        List<Source> sources,
        Artifacts files,
        CancellationToken ct)
    {
        var excerpts = CreateExcerpts(sources);
        await files.Save("research/source-excerpts.json", Data.Write(excerpts));
        var instructions = commonInstructions +
            $"\nSelect at least {config.MinClaims} useful historical claims from the numbered source excerpts. " +
            "Cover the subject using multiple independent source domains. " + ContentProfiles.Guidance(config.Profile) + " " +
            "For each claim, return id, text and excerptId. Copy excerptId exactly from the supplied list. " +
            "The selected excerpt must support the entire claim. Preserve uncertainty and qualify disputed accounts. " +
            "Do not transcribe, edit or invent quotations: application code will attach the exact saved excerpt. " +
            "Return ONLY JSON {\"claims\":[{\"id\":\"C1\",\"text\":string,\"excerptId\":\"S1-E001\"}]}.";

        string? feedback = null;
        LedgerSelection? previous = null;

        for (int pass = 1; pass <= config.MaxAttempts; pass++)
        {
            var prompt = Data.Write(new
            {
                subject,
                sources = sources.Select(source => new { source.Id, source.Url, source.Title, source.Sha256 }),
                excerpts,
                previousSelection = previous,
                validationFeedback = feedback
            });
            var selectionJson = await api.Agent(
                subject, "EvidenceLedgerAgent", "openrouter", config.WriterModel,
                instructions, prompt, files, $"ledger-{pass}", ct);
            previous = Data.Read<LedgerSelection>(selectionJson);
            await files.Save($"research/ledger-selection-{pass}.json", selectionJson);

            try
            {
                var ledger = Resolve(previous, excerpts, sources);
                researcher.Validate(ledger, sources);
                await files.Save("research/evidence-ledger.json", Data.Write(ledger));
                await files.Save("research/evidence-bindings.json", Data.Write(previous.Claims.Select(claim =>
                {
                    var excerpt = excerpts.Single(item => item.Id == claim.ExcerptId);
                    return new { claim.Id, claim.ExcerptId, excerpt.SourceId, excerpt.Start, excerpt.Length };
                })));
                log.LogInformation(
                    "[{Chapter}][EvidenceLedgerAgent][VERIFY] COMPLETE: {Count} claims bound to exact saved source excerpts",
                    subject, ledger.Claims.Count);

                return ledger;
            }
            catch (EditorialException exception)
            {
                feedback = exception.Message;
                await files.Save($"research/ledger-validation-{pass}.json", Data.Write(new
                {
                    approved = false,
                    reason = feedback,
                    attempt = pass
                }));
                log.LogWarning(
                    "[{Chapter}][EvidenceLedgerAgent][VERIFY] {Reason}; attempt {Pass}/{Limit}",
                    subject, feedback, pass, config.MaxAttempts);
            }
        }

        throw new EditorialException(
            $"Evidence verification remained unresolved after {config.MaxAttempts} attempts: {feedback}");
    }

    public static List<EvidenceExcerpt> CreateExcerpts(List<Source> sources)
    {
        var excerpts = new List<EvidenceExcerpt>();

        foreach (var source in sources)
        {
            if (source.Sha256 != Data.Hash(source.Text))
            {
                throw new EditorialException($"Source snapshot hash mismatch for {source.Id}.");
            }

            int start = 0;
            int number = 1;

            while (start < source.Text.Length)
            {
                while (start < source.Text.Length && char.IsWhiteSpace(source.Text[start]))
                {
                    start++;
                }

                if (start == source.Text.Length)
                {
                    break;
                }

                int end = Math.Min(start + 900, source.Text.Length);

                if (end < source.Text.Length)
                {
                    var sentenceEnd = source.Text.LastIndexOf(". ", end - 1, end - start, StringComparison.Ordinal);

                    if (sentenceEnd >= start + 300)
                    {
                        end = sentenceEnd + 1;
                    }
                    else
                    {
                        var wordEnd = source.Text.LastIndexOf(' ', end - 1, end - start);

                        if (wordEnd > start)
                        {
                            end = wordEnd;
                        }
                    }
                }

                int trimmedEnd = end;

                while (trimmedEnd > start && char.IsWhiteSpace(source.Text[trimmedEnd - 1]))
                {
                    trimmedEnd--;
                }

                if (trimmedEnd - start >= 30)
                {
                    excerpts.Add(new EvidenceExcerpt(
                        $"{source.Id}-E{number:D3}", source.Id, start, trimmedEnd - start,
                        source.Text[start..trimmedEnd]));
                    number++;
                }

                start = end;
            }
        }

        return excerpts;
    }

    public static Evidence Resolve(
        LedgerSelection selection,
        List<EvidenceExcerpt> excerpts,
        List<Source> sources)
    {
        if (selection.Claims is not { Count: > 0 })
        {
            throw new EditorialException("The ledger selection contains no claims.");
        }

        var claims = new List<Claim>();

        foreach (var selected in selection.Claims)
        {
            if (selected is null || string.IsNullOrWhiteSpace(selected.Id)
                || string.IsNullOrWhiteSpace(selected.Text) || string.IsNullOrWhiteSpace(selected.ExcerptId))
            {
                throw new EditorialException("Every selected claim requires id, text and excerptId.");
            }

            var excerpt = excerpts.SingleOrDefault(item => item.Id == selected.ExcerptId);

            if (excerpt is null)
            {
                throw new EditorialException(
                    $"Claim {selected.Id} references unknown excerpt {selected.ExcerptId}. Choose an ID from the supplied excerpts.");
            }

            var source = sources.SingleOrDefault(item => item.Id == excerpt.SourceId);

            if (source is null || excerpt.Start < 0 || excerpt.Length < 30
                || excerpt.Start > source.Text.Length - excerpt.Length
                || source.Sha256 != Data.Hash(source.Text)
                || source.Text.Substring(excerpt.Start, excerpt.Length) != excerpt.Quote)
            {
                throw new EditorialException($"Saved excerpt {excerpt.Id} no longer matches its source snapshot.");
            }

            claims.Add(new Claim(selected.Id, selected.Text, source.Id, excerpt.Quote));
        }

        return new Evidence(claims);
    }
}
