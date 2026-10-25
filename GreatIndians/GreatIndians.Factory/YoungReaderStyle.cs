using System.Text.RegularExpressions;

namespace GreatIndians.Factory;

public static class YoungReaderStyle
{
    private static readonly Regex ResearchCommentary = new(
        @"\bwe (?:do not|don't) know\b|\bsurrounded by uncertainty\b|\bmost of what (?:people|we|historians) know\b|\b(?:no|few) surviving (?:written |contemporary )?records\b|\b(?:parts|details) of (?:his|her|their) life (?:are|remain) uncertain\b|\bstories passed down (?:in|through) (?:different |various )?traditions\b",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    public static List<Finding> FindIssues(string chapter)
    {
        var findings = new List<Finding>();

        foreach (var paragraph in Regex.Split(chapter, @"(?:\r?\n){2,}"))
        {
            var text = Data.Normalize(paragraph);
            var match = ResearchCommentary.Match(text);

            if (!match.Success)
            {
                continue;
            }

            findings.Add(new Finding(
                "CHAPTER",
                "major",
                $"Child-facing research commentary contains the phrase '{match.Value}'.",
                "Remove this research-disclaimer paragraph. Retain supported biographical events in simple language; omit disputed details rather than stating them as fact. Keep source uncertainty in the separate review report."));
        }

        return findings;
    }
}
