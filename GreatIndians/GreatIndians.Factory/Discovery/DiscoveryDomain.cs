using System.Text.Json.Serialization;

namespace GreatIndians.Factory.Discovery;

public sealed record DiscoverySettings
{
    public int ChapterCount { get; init; } = 10;
    public string[] JurorModels { get; init; } =
        ["openai/gpt-4.1", "anthropic/claude-sonnet-4.5", "google/gemini-3.1-pro-preview"];
    public int MaxValidationAttempts { get; init; } = 2;
    public string Criteria { get; init; } =
        "Relevance to the title and scope; documented significance; credible evidence availability; " +
        "suitability and engagement for the configured reader age; distinct chapters and balanced coverage. " +
        "Do not mistake popularity for significance or claim an objective universal top-ten ranking.";

    public void Validate()
    {
        if (ChapterCount is < 1 or > 20 || MaxValidationAttempts is < 1 or > 3
            || string.IsNullOrWhiteSpace(Criteria) || JurorModels is not { Length: 3 }
            || JurorModels.Any(m => string.IsNullOrWhiteSpace(m) || !m.Contains('/') || m.Any(char.IsWhiteSpace))
            || JurorModels.Distinct(StringComparer.OrdinalIgnoreCase).Count() != 3)
            throw new InvalidDataException("Discovery requires 1–20 chapters, exactly three distinct OpenRouter model IDs, criteria and 1–3 validation attempts.");
    }
}

public sealed record NominatedTopic(
    [property: JsonRequired] string Name,
    [property: JsonRequired] string[] Aliases,
    [property: JsonRequired] string ImageQuery,
    [property: JsonRequired] string Rationale,
    [property: JsonRequired] string[] EvidenceExcerptIds);
public sealed record TopicNomination(
    [property: JsonRequired] string RecommendedProfile,
    [property: JsonRequired] string Scope,
    [property: JsonRequired] List<NominatedTopic> Candidates);
public sealed record TopicVote(
    [property: JsonRequired] string CandidateId,
    [property: JsonRequired] bool Approve,
    [property: JsonRequired] int Rank,
    [property: JsonRequired] string Reason,
    [property: JsonRequired] string[] EvidenceExcerptIds);
public sealed record TopicBallot(
    [property: JsonRequired] List<TopicVote> Votes,
    [property: JsonRequired] string Summary);

public sealed record JuryNomination(string JurorId, string Model, TopicNomination Nomination);
public sealed record JuryBallot(string JurorId, string Model, TopicBallot Ballot);
public sealed record DiscoveryCandidate(string Id, string Name, string[] Aliases, string ImageQuery,
    string Rationale, string[] EvidenceExcerptIds, string[] ProposedBy);
public sealed record CandidateDecision(DiscoveryCandidate Candidate, int YesVotes, double AverageRank,
    string[] ApprovingJurors, TopicVote[] Votes);

public sealed record ApprovedTopic(string Id, string Name, string[] ApprovingJurors);
public sealed record DiscoveryApproval
{
    public string InputFingerprint { get; init; } = "";
    public string RequestedProfile { get; init; } = "auto";
    public string SubjectListHash { get; init; } = "";
    public string[] JurorModels { get; init; } = [];
    public ApprovedTopic[] Topics { get; init; } = [];
    public string ReportPath { get; init; } = "";
    public string RunNonce { get; init; } = "";

    public void Validate(BookDefinition book)
    {
        if (JurorModels is not { Length: 3 } || JurorModels.Any(string.IsNullOrWhiteSpace)
            || JurorModels.Distinct(StringComparer.OrdinalIgnoreCase).Count() != 3
            || Topics is null || Topics.Length != book.Subjects.Length
            || Topics.Any(t => t is null)
            || SubjectListHash != DiscoveryPolicy.SubjectHash(book.Title, book.Profile, book.Subjects)
            || !Topics.Select(t => (t.Id, t.Name)).SequenceEqual(book.Subjects.Select(s => (s.Id, s.Name)))
            || Topics.Any(t => t is null || t.ApprovingJurors is null || t.ApprovingJurors.Distinct().Count() < 2
                || t.ApprovingJurors.Distinct().Count() != t.ApprovingJurors.Length
                || t.ApprovingJurors.Any(id => !DiscoveryPolicy.JurorIds.Contains(id))))
            throw new InvalidDataException("Discovery approval does not match this title/profile/ordered subject list or lacks a two-of-three majority. Rerun discovery after changing topics.");
    }
}

public sealed class DiscoveryConsensusException(string message) : Exception(message);
