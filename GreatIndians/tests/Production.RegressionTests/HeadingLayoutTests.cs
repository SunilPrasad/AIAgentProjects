using System.IO.Compression;
using System.Xml.Linq;
using GreatIndians.Factory;
using GreatIndians.Factory.Production;

internal static class HeadingLayoutTests
{
    private static void Check(bool valid, string message)
    {
        if (!valid) throw new Exception("Section heading layout: " + message);
    }

    public static void Run()
    {
        string root = Path.Combine(AppContext.BaseDirectory, "heading-proofs", Guid.NewGuid().ToString("N")[..10]);
        Directory.CreateDirectory(root);
        string path = Path.Combine(root, "01-heading-fixture.md");
        var config = new ProductionConfig { Subjects = ["Heading Fixture"], IllustrationCount = 1 };
        string paragraph = "This paragraph is an offline layout fixture. Its original words must remain unchanged in the printed edition. " +
            "Smaller section headings guide the reader through the chapter without competing with the main title. " +
            "Each heading stays with the beginning of the next paragraph. The text continues naturally across page boundaries, " +
            "while the font size, margins and spacing remain comfortable for young readers.";
        string markdown = "# Heading Fixture: A Chapter with Smaller Section Headings\n\n## Early Life and Education\n\n" +
            string.Join("\n\n", Enumerable.Repeat(paragraph, 3)) +
            "\n\n## Discoveries and a Longer Section Heading That Wraps Naturally across More Than One Line\n\n" +
            string.Join("\n\n", Enumerable.Repeat(paragraph, 4)) +
            "\n\n## Lasting Influence\n\n### Sharing Ideas with Young Readers\n\n" +
            string.Join("\n\n", Enumerable.Repeat(paragraph, 3));
        File.WriteAllText(path, markdown);
        var manuscript = ManuscriptReader.Load(path, config);
        Check(manuscript.Headings.Count == 4 && manuscript.Paragraphs.Count == 10, "Source headings/paragraphs were lost.");
        Check(manuscript.Headings[0].BeforeParagraphId == "P001" && manuscript.Headings[1].BeforeParagraphId == "P004"
            && manuscript.Headings[2].BeforeParagraphId == "P008" && manuscript.Headings[3].BeforeParagraphId == "P008",
            "Heading anchors changed paragraph IDs or positions.");
        string pdfPath = Path.Combine(root, "section-headings.pdf");
        var layout = ChapterPdfLayout.Create(manuscript, [], config, pdfPath);
        var checks = ChapterPdfLayout.Verify(pdfPath, manuscript, layout, config);
        Check(checks.Passed, string.Join("; ", checks.Issues));
        Check(layout.Text.Where(t => t.Kind == "title").All(t => t.Page == 1), "Main title was repeated.");
        Check(layout.Text.Any(t => t.Kind == "heading" && t.Page > 1), "Later-page section headings were not exercised.");
        foreach (var heading in manuscript.Headings)
        {
            var placed = layout.Text.Where(t => t.Kind == "heading" && t.ParagraphId == heading.Id).ToList();
            var following = layout.Text.First(t => t.Kind == "paragraph" && t.ParagraphId == heading.BeforeParagraphId);
            Check(placed.Count > 0 && placed.All(t => t.Page == following.Page && t.Y < following.Y), "Orphaned section heading.");
        }
        var missing = layout with { Text = layout.Text.Where(t => t.Kind != "heading").ToList() };
        Check(ChapterPdfLayout.Verify(pdfPath, manuscript, missing, config).Issues.Any(i => i.Contains("Section heading")),
            "Missing heading passed exact-text verification.");
        var orphan = layout with { Text = layout.Text.Select(t => t.Kind == "heading" ? t with { Page = t.Page + 1 } : t).ToList() };
        Check(ChapterPdfLayout.Verify(pdfPath, manuscript, orphan, config).Issues.Any(i => i.Contains("separated")),
            "Orphan heading passed verification.");
        string epubPath = Path.ChangeExtension(pdfPath, ".epub");
        ChapterEpub.Create(manuscript, [], config, epubPath);
        using (var epub = ZipFile.OpenRead(epubPath))
        using (var stream = epub.GetEntry("OEBPS/chapter.xhtml")!.Open())
        {
            var doc = XDocument.Load(stream);
            XNamespace html = "http://www.w3.org/1999/xhtml";
            Check(doc.Descendants(html + "h1").Count() == 1 && doc.Descendants(html + "h2").Count() == 3
                && doc.Descendants(html + "h3").Count() == 1, "EPUB heading hierarchy lost.");
        }
        Check(File.ReadAllText(path) == markdown, "Authoritative source was rewritten.");
        File.WriteAllText(path, markdown + "\n\n## A heading without a paragraph\n");
        bool trailingRejected = false;
        try { ManuscriptReader.Load(path, config); } catch (InvalidDataException) { trailingRejected = true; }
        Check(trailingRejected, "Dangling heading was silently omitted.");
        File.WriteAllText(path, markdown);
        var previews = ChapterPdfLayout.RenderPages(pdfPath, Path.Combine(root, "previews"));
        Check(previews.Count == layout.PageCount, "Not every page was rendered.");
        Console.WriteLine($"PASS retained section headings: 22pt title / 14pt bold headings / 12.1pt body; exact PDF/EPUB text, hierarchy, wrapping and no orphan headings. Proof: {pdfPath}");
        Console.WriteLine("Rendered heading proof pages: " + string.Join(", ", previews));
    }
}
