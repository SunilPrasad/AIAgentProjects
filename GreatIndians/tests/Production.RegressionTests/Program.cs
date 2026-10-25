using System.Text.Json;
using System.Text.Json.Nodes;
using GreatIndians.Factory;
using GreatIndians.Factory.Production;
using SkiaSharp;

// Native layout and acceptance-gate regression tests. No API client or network calls.
var root = Path.Combine(AppContext.BaseDirectory, "proofs", Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
var config = new ProductionConfig();
var input = args.Length > 0 ? Path.GetFullPath(args[0]) : Path.Combine(root, "manuscripts");
if (args.Length == 0)
{
    Directory.CreateDirectory(input);
    for (int index = 0; index < config.Subjects.Length; index++)
    {
        var paragraphs = Enumerable.Range(1, 12 + index % 3).Select(number =>
            $"Paragraph {number} retains its own exact words, punctuation, and order. " +
            "This is a **layout test**, with *italic words*, a long sentence and ordinary punctuation. " +
            "The illustrations are geometric placeholders; they make no historical claims. " +
            "Every printed line must stay selectable, readable and inside the safe margins. " +
            "The layout may resize an illustration proportionally but must never shorten this paragraph to fit a page.");
        File.WriteAllText(Path.Combine(input, $"{index + 1:D2}-fixture.md"),
            $"# {config.Subjects[index]} — Offline layout fixture\n\n" + string.Join("\n\n", paragraphs));
    }
}
var fixtureReview = new ImageReview(true, true, true, true, true, true, true, true, true, true, [])
{
    ReferenceColourAndLightMatch = true,
    PainterlyDetailMatches = true,
    CharacterFeaturesMatch = true,
    StyleComparison = "OFFLINE geometric placeholder; not a real visual approval.",
    CharacterComparison = "OFFLINE identity fixture; not a real visual approval."
};

Check(fixtureReview.Passes, "Complete fixture review should pass.");
foreach (var rejected in new[]
{
    fixtureReview with { ReferenceColourAndLightMatch = false },
    fixtureReview with { PainterlyDetailMatches = false },
    fixtureReview with { CharacterFeaturesMatch = false },
    fixtureReview with { ConsistentCharacter = false },
    fixtureReview with { FullHeadVisible = false },
    fixtureReview with { StyleComparison = "" },
    fixtureReview with { CharacterComparison = "" }
})
{
    Check(!rejected.Passes, "Style, identity, crop or missing comparison was accepted.");
}
var incomplete = JsonNode.Parse(Data.Write(fixtureReview))!.AsObject();
incomplete.Remove(nameof(ImageReview.CharacterFeaturesMatch));
bool rejectedMissingField = false;
try { Data.Read<ImageReview>(incomplete.ToJsonString()); }
catch (JsonException) { rejectedMissingField = true; }
Check(rejectedMissingField, "A review omitting mandatory character comparison was accepted.");
Console.WriteLine("PASS style/character/cropping gates and required review fields");

var sources = Directory.GetFiles(input, "*.md").Order().ToArray();
Check(sources.Length == 10, "Expected ten chapter manuscripts.");
foreach (var source in sources)
{
    var manuscript = ManuscriptReader.Load(source, config);
    var artwork = new List<AcceptedArtwork>();
    // Intentionally cluster the first two anchors, reproducing the old whitespace trigger.
    int[] anchors = [0, 1, manuscript.Paragraphs.Count / 2, manuscript.Paragraphs.Count - 2];
    for (int index = 0; index < anchors.Length; index++)
    {
        var paragraph = manuscript.Paragraphs[anchors[index]];
        var scene = new IllustrationScene($"I{index + 1:D2}", manuscript.Subject, [paragraph.Id], paragraph.Id,
            "Offline geometric layout fixture", "3:2", "No historical claim", ["text"], "Geometric test image");
        var imagePath = Path.Combine(root, $"{manuscript.ChapterNumber}-{scene.Id}.png");
        using var bitmap = new SKBitmap(1800, 1200);
        using var canvas = new SKCanvas(bitmap);
        canvas.Clear(new SKColor(40, 185, 194));
        using var paint = new SKPaint { Color = new SKColor(248, 201, 77), IsAntialias = true };
        canvas.DrawCircle(900, 600, 350, paint);
        using var image = bitmap.Encode(SKEncodedImageFormat.Png, 100);
        File.WriteAllBytes(imagePath, image.ToArray());
        artwork.Add(new AcceptedArtwork(scene, imagePath, ManuscriptReader.HashFile(imagePath),
            bitmap.Width, bitmap.Height, fixtureReview));
    }

    var pdf = Path.Combine(root, $"chapter-{manuscript.ChapterNumber:D2}.pdf");
    var layout = ChapterPdfLayout.Create(manuscript, artwork, config, pdf);
    var checks = ChapterPdfLayout.Verify(pdf, manuscript, layout, config);
    Check(checks.Passed, manuscript.Subject + ": " + string.Join("; ", checks.Issues));
    Check(layout.Images.Count == artwork.Count, "Missing illustration.");
    Check(layout.Images.All(i => i.EffectiveDpi >= 300), "Low-resolution placement.");
    Check(!Directory.GetFiles(root, ".layout-*.pdf").Any(), "Unselected local candidates were left behind.");
    foreach (var placement in layout.Images)
    {
        var art = artwork.Single(a => a.Scene.Id == placement.SceneId);
        Check(Math.Abs(placement.Width / placement.Height - (double)art.PixelWidth / art.PixelHeight) < 0.001,
            "Illustration was stretched or cropped.");
        var paragraph = layout.Text.First(t => t.ParagraphId == art.Scene.InsertBeforeParagraphId);
        Check(placement.Page == paragraph.Page && placement.Y + placement.Height < paragraph.Y,
            "Illustration moved away from its narrative anchor.");
    }
    ChapterEpub.Create(manuscript, artwork, config, Path.ChangeExtension(pdf, ".epub"));
    ManuscriptReader.VerifySourceUnchanged(manuscript);

    // Prove that a two-line continuation cannot be silently approved again.
    var sparse = layout with
    {
        Text = layout.Text.Where(t => t.Page != layout.PageCount || t.Kind == "footer")
            .Concat(layout.Text.Where(t => t.Page == layout.PageCount && t.Kind == "paragraph").Take(2)).ToList(),
        Images = layout.Images.Where(i => i.Page != layout.PageCount).ToList()
    };
    Check(ChapterPdfLayout.Verify(pdf, manuscript, sparse, config).Issues.Any(i => i.Contains("Nearly empty")),
        "Sparse continuation page was not flagged.");
    Console.WriteLine($"PASS {manuscript.Subject}: {layout.PageCount} pages, exact PDF/EPUB text, safe images and no sparse tail");
}
Console.WriteLine($"Offline proofs: {root}");
Console.WriteLine("These tests verify layout and rejection logic, not the quality of live model-generated artwork.");

static void Check(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}
