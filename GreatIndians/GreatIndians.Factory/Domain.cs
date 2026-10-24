using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace GreatIndians.Factory;

public sealed record BookConfig
{
    public string BookTitle { get; init; } = "Great Indians Who Changed History";
    public int AudienceMinAge { get; init; } = 8;
    public int AudienceMaxAge { get; init; } = 12;
    public string Language { get; init; } = "British English";
    public int ChapterWordCountMin { get; init; } = 600;
    public int ChapterWordCountMax { get; init; } = 900;
    public List<string> Personalities { get; init; } = [];
    public string StyleBible { get; init; } = "style-bible.md";
    public string OutputDirectory { get; init; } = "output";
    public string WriterModel { get; init; } = "openai/gpt-4.1";
    public string ResearchModel { get; init; } = "openai/gpt-4.1";
    public string ReviewerModel { get; init; } = "anthropic/claude-sonnet-4.5";
    public int MaxReviewPasses { get; init; } = 3;
    public int MaxAttempts { get; init; } = 3;
    public int MinSources { get; init; } = 2;
    public int MinClaims { get; init; } = 8;
    public int MaxSources { get; init; } = 6;
    public int MaxSourceCharacters { get; init; } = 18000;
    public List<string> AllowedSourceDomains { get; init; } = [];
    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(BookTitle) || Personalities is null || Personalities.Count == 0 || Personalities.Any(string.IsNullOrWhiteSpace)
            || Personalities.Distinct(StringComparer.OrdinalIgnoreCase).Count() != Personalities.Count
            || AudienceMinAge < 1 || AudienceMaxAge < AudienceMinAge || ChapterWordCountMin < 1
            || ChapterWordCountMax < ChapterWordCountMin || MaxReviewPasses is < 1 or > 10 || MaxAttempts is < 1 or > 5
            || MinSources < 2 || MaxSources < MinSources || MaxSources > 10 || MinClaims < 1
            || MaxSourceCharacters is < 1000 or > 50000 || AllowedSourceDomains is null
            || new[] { WriterModel, ResearchModel, ReviewerModel, StyleBible, OutputDirectory }.Any(string.IsNullOrWhiteSpace)
            || new[] { WriterModel, ResearchModel, ReviewerModel }.Any(model => !model.Contains('/') || model.Any(char.IsWhiteSpace)))
        {
            throw new InvalidDataException("Invalid book configuration. Check personalities, OpenRouter model IDs (author/model), bounds and retry limits.");
        }
    }
}
public sealed record Source(string Id, string Url, string Title, string Text, string Sha256, DateTimeOffset RetrievedAt);
public sealed record Evidence([property: JsonRequired] List<Claim> Claims);
public sealed record Claim([property: JsonRequired] string Id, [property: JsonRequired] string Text,
    [property: JsonRequired] string SourceId, [property: JsonRequired] string Quote);
public sealed record Finding([property: JsonRequired] string ClaimId, [property: JsonRequired] string Severity,
    [property: JsonRequired] string Issue, [property: JsonRequired] string RecommendedFix);
public sealed record Review([property: JsonRequired] bool Approved, [property: JsonRequired] List<Finding> Findings,
    [property: JsonRequired] string Summary)
{
    public void Validate()
    {
        if (Findings is null || string.IsNullOrWhiteSpace(Summary) || Findings.Any(f => f is null
            || string.IsNullOrWhiteSpace(f.ClaimId) || string.IsNullOrWhiteSpace(f.Issue) || string.IsNullOrWhiteSpace(f.RecommendedFix)
            || !new[] { "critical", "major", "minor" }.Contains(f.Severity)) || (Approved && Findings.Any(finding => finding.Severity is "critical" or "major")))
        {
            throw new InvalidDataException("Invalid or inconsistent review; approval withheld.");
        }
    }
}
public sealed record ChapterState(string Subject, List<Source> Sources, Evidence? Ledger = null,
    string Outline = "", string Draft = "", int Pass = 0, List<Review>? Reviews = null, bool Approved = false,
    List<ReviewerFailure>? ReviewFailures = null, List<ChapterCandidate>? Candidates = null);
public sealed record ChapterResult(
    string Subject, string Status, string Directory, string? ContentHash, string Reason,
    string? ChapterPath = null, string? ReviewPath = null, int? SelectedPass = null,
    bool IsFinalGenerated = false, bool PublicationApproved = false);
public sealed class EditorialException(string message) : Exception(message);

public static class Data
{
    public static readonly JsonSerializerOptions Json = new() { PropertyNameCaseInsensitive = true, WriteIndented = true };
    public static T Read<T>(string value) => JsonSerializer.Deserialize<T>(value, Json) ?? throw new InvalidDataException("Empty JSON result.");
    public static string Write<T>(T value) => JsonSerializer.Serialize(value, Json);
    public static string Hash(string value) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
    public static string Slug(string value) => Regex.Replace(value.ToLowerInvariant(), "[^a-z0-9]+", "-").Trim('-');
    public static string Normalize(string value) => Regex.Replace(value, @"\s+", " ").Trim();
    public static string JsonObject(string value)
    {
        value = value.Trim();
        if (value.StartsWith("```"))
        {
            var line = value.IndexOf('\n');
            if (line < 0 || !value.EndsWith("```"))
            {
                throw new InvalidDataException("Incomplete JSON fence.");
            }

            value = value[(line + 1)..^3].Trim();
        }
        using var doc = JsonDocument.Parse(value);
        if (doc.RootElement.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException("Expected a JSON object.");
        }

        return value;
    }
    public static async Task SaveAsync(string path, string text)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temp = path + ".tmp-" + Guid.NewGuid().ToString("N");
        await File.WriteAllTextAsync(temp, text);
        File.Move(temp, path, overwrite: true);
    }
}
