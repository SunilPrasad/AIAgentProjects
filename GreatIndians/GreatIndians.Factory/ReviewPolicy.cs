namespace GreatIndians.Factory;

public sealed record ReviewerFailure(string Agent, string Reason);
public sealed record ReviewOutcome(string Agent, Review? Review, ReviewerFailure? Failure);
public sealed record ChapterCandidate(
    string Draft,
    int Pass,
    List<Review> Reviews,
    List<ReviewerFailure> Failures,
    int WordCount,
    bool Approved);

public static class ReviewPolicy
{
    public static int WordCount(string text)
        => System.Text.RegularExpressions.Regex.Matches(
            text, @"\b[\p{L}\p{N}]+(?:['’-][\p{L}\p{N}]+)*\b").Count;

    public static bool PassesMandatoryChecks(IEnumerable<Review> reviews)
        => reviews.Any() && reviews.All(review =>
            !review.Findings.Any(finding => finding.Severity is "critical" or "major")
            && (review.Approved || review.Findings.Count > 0));

    public static ChapterCandidate Best(IEnumerable<ChapterCandidate> candidates, BookConfig config)
        => candidates
            .OrderBy(candidate => candidate.Approved ? 0 : 1)
            .ThenBy(candidate => candidate.Failures.Count)
            .ThenBy(candidate => candidate.Reviews.Sum(review => review.Findings.Count(finding => finding.Severity == "critical")))
            .ThenBy(candidate => candidate.Reviews.Sum(review => review.Findings.Count(finding => finding.Severity == "major")))
            .ThenBy(candidate => Math.Max(0, candidate.WordCount - config.ChapterWordCountMax)
                + Math.Max(0, config.ChapterWordCountMin - candidate.WordCount))
            .ThenBy(candidate => candidate.Reviews.Sum(review => review.Findings.Count(finding => finding.Severity == "minor")))
            .ThenByDescending(candidate => candidate.Pass)
            .First();
}
