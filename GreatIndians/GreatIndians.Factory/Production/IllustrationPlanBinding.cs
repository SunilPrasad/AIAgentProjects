namespace GreatIndians.Factory.Production;

/// <summary>Binds production metadata without rewriting any manuscript or scene description.</summary>
public static class IllustrationPlanBinding
{
    public static IllustrationPlan Bind(Manuscript manuscript, IllustrationPlan plan, List<string> adjustments)
    {
        // Never repair a different historical identity into an apparently valid plan.
        if (plan.Character?.Name != manuscript.Subject || plan.Scenes is null)
            return plan;

        var scenes = new List<IllustrationScene>();
        int previous = -1;
        for (int index = 0; index < plan.Scenes.Count; index++)
        {
            var scene = plan.Scenes[index];
            if (index == 0 && scene.AspectRatio == "3:4")
            {
                scene = scene with { AspectRatio = "3:2" };
                adjustments.Add($"{scene.Id}: set landscape 3:2 opening composition for the approved page style.");
            }
            var paragraphs = scene.ParagraphIds?.ToList();
            if (index == 0 && paragraphs is { Count: 0 })
            {
                paragraphs.Add(manuscript.Paragraphs[0].Id);
                adjustments.Add($"{scene.Id}: bound opening portrait to {paragraphs[0]}.");
            }

            var subject = scene.Subject;
            // The model often supplies a scene topic here. Identity comes from the validated character
            // and manuscript, while the original topic remains in the retained raw response.
            if (subject != manuscript.Subject && !ContainsOtherSubject(subject, manuscript.Subject))
            {
                subject = manuscript.Subject;
                adjustments.Add($"{scene.Id}: bound subject metadata to {manuscript.Subject}.");
            }

            var anchor = scene.InsertBeforeParagraphId;
            int position = manuscript.Paragraphs.FindIndex(p => p.Id == anchor);
            if (paragraphs is { Count: > 0 }
                && paragraphs.All(id => manuscript.Paragraphs.Any(p => p.Id == id))
                && (position <= previous || !paragraphs.Contains(anchor) || index == 0 && position != 0))
            {
                var candidates = manuscript.Paragraphs.Select((p, i) => (p.Id, Index: i))
                    .Where(p => paragraphs.Contains(p.Id) && p.Index > previous && (index != 0 || p.Index == 0))
                    .ToList();
                if (candidates.Count > 0)
                {
                    anchor = candidates[0].Id;
                    position = candidates[0].Index;
                    adjustments.Add($"{scene.Id}: placed before its retained source paragraph {anchor}.");
                }
            }
            scenes.Add(scene with { Subject = subject, ParagraphIds = paragraphs!, InsertBeforeParagraphId = anchor });
            previous = position;
        }
        return plan with { Scenes = scenes };
    }

    private static bool ContainsOtherSubject(string? value, string expected)
        => new ProductionConfig().Subjects.Where(subject => subject != expected)
            .Any(subject => value?.Contains(subject, StringComparison.OrdinalIgnoreCase) == true);
}
