using System.Text;
using System.Text.RegularExpressions;

namespace GreatIndians.Factory.Discovery;

public static class DiscoveryPolicy
{
    public static readonly string[] JurorIds = ["juror-1", "juror-2", "juror-3"];
    public static string NormalizedName(string value) => Regex.Replace(
        value.Normalize(NormalizationForm.FormKD).ToLowerInvariant(), "[^\\p{L}\\p{N}]", "");
    public static string SubjectHash(string title, string profile, IEnumerable<SubjectDefinition> subjects)
        => Data.Hash(Data.Write(new { title, profile, topics = subjects.Select(s => new { s.Id, s.Name }) }));

    public static void ValidateNomination(TopicNomination nomination, IReadOnlyList<EvidenceExcerpt> excerpts, int limit)
    {
        if (!ContentProfiles.All.Contains(nomination.RecommendedProfile) || string.IsNullOrWhiteSpace(nomination.Scope)
            || nomination.Candidates is not { Count: > 0 } || nomination.Candidates.Count > limit)
            throw new InvalidDataException("Supply a supported profile, scope and 1 to the requested maximum candidates.");
        var known = excerpts.Select(e => e.Id).ToHashSet(StringComparer.Ordinal);
        if (nomination.Candidates.Any(c => c is null || string.IsNullOrWhiteSpace(c.Name)
            || string.IsNullOrWhiteSpace(c.Rationale) || string.IsNullOrWhiteSpace(c.ImageQuery)
            || c.Aliases is null || c.Aliases.Any(string.IsNullOrWhiteSpace)
            || c.EvidenceExcerptIds is not { Length: > 0 } || c.EvidenceExcerptIds.Any(id => !known.Contains(id))))
            throw new InvalidDataException("Every candidate needs its canonical name, aliases, image query, rationale and valid retained evidence excerpt IDs.");
        if (nomination.Candidates.Select(c => NormalizedName(c.Name)).Distinct().Count() != nomination.Candidates.Count)
            throw new InvalidDataException("Do not nominate the same candidate twice under punctuation/case variants.");
    }

    public static List<DiscoveryCandidate> Merge(IEnumerable<JuryNomination> nominations, SubjectDefinition[] existing)
    {
        var pool = new List<DiscoveryCandidate>();
        foreach (var jury in nominations.OrderBy(n => n.JurorId, StringComparer.Ordinal))
        foreach (var entry in jury.Nomination.Candidates)
        {
            string canonical = NormalizedName(entry.Name);
            var old = existing.Where(s => new[] { s.Name }.Concat(s.Aliases).Any(n => NormalizedName(n) == canonical)).ToList();
            if (old.Count > 1) throw new InvalidDataException("Candidate name ambiguously matches more than one existing subject.");
            var previous = old.SingleOrDefault();
            string name = previous?.Name ?? entry.Name.Trim();
            string id = previous?.Id ?? Data.Slug(name);
            if (id.Length == 0) id = "topic-" + Data.Hash(name)[..12];
            var aliases = entry.Aliases.Concat(previous?.Aliases ?? []).Select(n => n.Trim())
                .Where(n => NormalizedName(n) != NormalizedName(name)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
            // Canonical-to-alias matching is allowed; shared surnames in alias lists alone never merge two people.
            var matches = pool.Where(c => NormalizedName(c.Name) == NormalizedName(name)
                || c.Aliases.Any(a => NormalizedName(a) == NormalizedName(name))
                || aliases.Any(a => NormalizedName(a) == NormalizedName(c.Name))).ToList();
            var evidence = entry.EvidenceExcerptIds.Concat(matches.SelectMany(c => c.EvidenceExcerptIds)).Distinct().Order().ToArray();
            var proposedBy = matches.SelectMany(c => c.ProposedBy).Append(jury.JurorId).Distinct().Order().ToArray();
            if (matches.Count > 0)
            {
                var keep = matches.OrderBy(c => c.Id, StringComparer.Ordinal).First();
                id = keep.Id; name = keep.Name;
                aliases = aliases.Concat(matches.SelectMany(c => c.Aliases.Append(c.Name)))
                    .Where(n => NormalizedName(n) != NormalizedName(name)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
                foreach (var match in matches) pool.Remove(match);
            }
            if (pool.Any(c => c.Id == id)) id += "-" + Data.Hash(name)[..8];
            pool.Add(new DiscoveryCandidate(id, name, aliases, previous?.ImageQuery is { Length: > 0 } query ? query : entry.ImageQuery,
                matches.FirstOrDefault()?.Rationale ?? entry.Rationale, evidence, proposedBy));
        }
        // Remove ambiguous display aliases so two distinct people cannot share a lookup key.
        return pool.OrderBy(c => c.Id, StringComparer.Ordinal).Select(c => c with
        {
            Aliases = c.Aliases.Where(a => !pool.Any(other => other.Id != c.Id
                && other.Aliases.Append(other.Name).Any(n => NormalizedName(n) == NormalizedName(a)))).ToArray()
        }).ToList();
    }

    public static void ValidateBallot(TopicBallot ballot, IReadOnlyList<DiscoveryCandidate> pool)
    {
        if (ballot.Votes is null || string.IsNullOrWhiteSpace(ballot.Summary) || ballot.Votes.Count != pool.Count
            || ballot.Votes.Any(v => v is null) || ballot.Votes.Select(v => v.CandidateId).Distinct().Count() != pool.Count
            || !ballot.Votes.Select(v => v.CandidateId).ToHashSet().SetEquals(pool.Select(c => c.Id)))
            throw new InvalidDataException("Vote exactly once on every candidate ID, without adding, omitting or duplicating candidates.");
        foreach (var vote in ballot.Votes)
        {
            var candidate = pool.Single(c => c.Id == vote.CandidateId);
            if (string.IsNullOrWhiteSpace(vote.Reason) || vote.EvidenceExcerptIds is null
                || vote.EvidenceExcerptIds.Any(id => !candidate.EvidenceExcerptIds.Contains(id))
                || vote.Approve && (vote.Rank < 1 || vote.EvidenceExcerptIds.Length == 0)
                || !vote.Approve && vote.Rank != 0)
                throw new InvalidDataException("Approvals need a positive rank and supporting candidate evidence; rejections need rank 0; all votes need reasons.");
        }
        var ranks = ballot.Votes.Where(v => v.Approve).Select(v => v.Rank).Order().ToArray();
        if (!ranks.SequenceEqual(Enumerable.Range(1, ranks.Length)))
            throw new InvalidDataException("Rank approved candidates consecutively from 1, without duplicates.");
    }

    public static List<CandidateDecision> Tally(IReadOnlyList<DiscoveryCandidate> pool, IReadOnlyList<JuryBallot> ballots)
    {
        if (ballots.Count != 3 || !ballots.Select(b => b.JurorId).ToHashSet().SetEquals(JurorIds)
            || ballots.Select(b => b.Model).Distinct(StringComparer.OrdinalIgnoreCase).Count() != 3)
            throw new InvalidDataException("Exactly three distinct juror ballots are required; unavailable jurors are not counted as approvals.");
        foreach (var ballot in ballots) ValidateBallot(ballot.Ballot, pool);
        return pool.Select(c =>
        {
            var votes = ballots.Select(b => b.Ballot.Votes.Single(v => v.CandidateId == c.Id)).ToArray();
            var yes = ballots.Where(b => b.Ballot.Votes.Single(v => v.CandidateId == c.Id).Approve).Select(b => b.JurorId).Order().ToArray();
            return new CandidateDecision(c, yes.Length, votes.Any(v => v.Approve)
                ? votes.Where(v => v.Approve).Average(v => v.Rank) : double.MaxValue, yes, votes);
        }).OrderByDescending(d => d.YesVotes).ThenBy(d => d.AverageRank).ThenBy(d => d.Candidate.Id, StringComparer.Ordinal).ToList();
    }
}
