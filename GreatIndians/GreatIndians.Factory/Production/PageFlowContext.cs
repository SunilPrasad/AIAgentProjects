namespace GreatIndians.Factory.Production;

public sealed record ParagraphFlow(string ParagraphId, bool StartedOnEarlierPage, bool ContinuesOnLaterPage);
public sealed record PageFlowContext(
    int PageNumber, int TotalPages, List<TextPlacement> PreviousPageEnding,
    List<TextPlacement> NextPageBeginning, List<ParagraphFlow> Paragraphs)
{
    public static PageFlowContext From(LayoutManifest layout, int pageNumber)
    {
        if (pageNumber < 1 || pageNumber > layout.PageCount)
            throw new ArgumentOutOfRangeException(nameof(pageNumber));

        var narrative = layout.Text.Where(t => t.Kind == "paragraph").ToList();
        var paragraphs = narrative.Where(t => t.Page == pageNumber && t.ParagraphId is not null)
            .Select(t => t.ParagraphId!).Distinct().Select(id => new ParagraphFlow(id,
                narrative.Any(t => t.ParagraphId == id && t.Page < pageNumber),
                narrative.Any(t => t.ParagraphId == id && t.Page > pageNumber))).ToList();
        return new PageFlowContext(pageNumber, layout.PageCount,
            narrative.Where(t => t.Page == pageNumber - 1).TakeLast(3).ToList(),
            narrative.Where(t => t.Page == pageNumber + 1).Take(3).ToList(), paragraphs);
    }
}
