namespace GreatIndians.Factory.Production;

public static class PageImageContext
{
    public static object For(Manuscript manuscript, AcceptedArtwork art)
    {
        var passages = manuscript.Paragraphs.Where(p => art.Scene.ParagraphIds.Contains(p.Id)).Select(p => new { p.Id, p.Text });
        if (art.Credit is not null)
            return new
            {
                sourceKind = "wikimedia-photograph", sceneId = art.Scene.Id,
                insertBeforeParagraphId = art.Scene.InsertBeforeParagraphId,
                acceptedPhotograph = new { art.Credit.Title, art.Credit.SourceUrl, art.Review.VisibleIdentity, art.Review.OverallScore },
                passages
            };
        return new { sourceKind = "generated-illustration", art.Scene, art.Review.OverallScore, art.Review.Suggestions, passages };
    }

    public static bool CanFixByRelayout(PageReview review) => review.CorrectSubject && review.ImagesMatchPassages;
}
