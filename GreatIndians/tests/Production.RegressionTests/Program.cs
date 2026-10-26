using System.Text.Json;
using System.Text.Json.Nodes;
using GreatIndians.Factory;
using GreatIndians.Factory.Production;
using SkiaSharp;

// Native layout and acceptance-gate regression tests. No API client or network calls.
ImageReviewSettingsTests.Run();
await CommonsSearchTests.RunAsync();
if (args.Contains("--commons-only")) return;
await ApiRecoveryTests.RunAsync();
if (args.Contains("--api-only")) return;
HeadingLayoutTests.Run();
if (args.Contains("--headings-only")) return;
await CostMeterTests.RunAsync();
await DiscoveryTests.RunAsync();
if (args.Contains("--discovery-only")) return;
var root = Path.Combine(AppContext.BaseDirectory, "proofs", Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
await GenericBookTests.RunAsync(root);
if (args.Contains("--generic-only")) return;
var config = new ProductionConfig();
var flowFixture = new LayoutManifest(432, 648, 54.96, 3, [],
[
    new("paragraph", "P004", 1, 55, 550, "He worked to keep"),
    new("footer", null, 1, 216, 615, "1"),
    new("paragraph", "P004", 2, 50, 54, "the new government stable."),
    new("paragraph", "P005", 2, 50, 90, "Another paragraph begins and"),
    new("paragraph", "P005", 3, 55, 54, "continues on the final page.")
], "offline-flow-fixture");
var firstFlow = PageFlowContext.From(flowFixture, 1);
var middleFlow = PageFlowContext.From(flowFixture, 2);
var finalFlow = PageFlowContext.From(flowFixture, 3);
Check(firstFlow.PreviousPageEnding.Count == 0 && firstFlow.Paragraphs.Single().ContinuesOnLaterPage,
    "First-page continuation was not identified.");
Check(firstFlow.NextPageBeginning.First().Text == "the new government stable.", "Next-page context is missing.");
Check(middleFlow.PreviousPageEnding.Single().Text == "He worked to keep", "Footer leaked into narrative context.");
Check(middleFlow.Paragraphs.Single(p => p.ParagraphId == "P004").StartedOnEarlierPage
    && middleFlow.Paragraphs.Single(p => p.ParagraphId == "P005").ContinuesOnLaterPage,
    "Distinct incoming/outgoing paragraphs were confused.");
Check(finalFlow.NextPageBeginning.Count == 0 && !finalFlow.Paragraphs.Single().ContinuesOnLaterPage,
    "A continuation beyond the final page was invented.");
Console.WriteLine("PASS page-boundary context, incoming/outgoing paragraphs and final-page boundaries");
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
            "The layout may resize an illustration proportionally but must never shorten this paragraph to fit a page.").ToArray();
        File.WriteAllText(Path.Combine(input, $"{index + 1:D2}-fixture.md"),
            $"# {config.Subjects[index]} — Offline layout fixture\n\n" + string.Join("\n\n", paragraphs.Select((p, position) =>
                position is 0 or 1 || position == paragraphs.Length / 2 || position == paragraphs.Length - 2
                    ? $"## Section {position + 1}: A Smaller Paragraph Heading\n\n{p}" : p)));
    }
}
var fixtureReview = new ImageReview(true, true, true, true, true, true, true, true, true, true, [])
{
    ReferenceColourAndLightMatch = true,
    PainterlyDetailMatches = true,
    CharacterFeaturesMatch = true,
    StyleScore = 75,
    CharacterScore = 75,
    QualityScore = 75,
    StyleComparison = "OFFLINE geometric placeholder; not a real visual approval.",
    CharacterComparison = "OFFLINE identity fixture; not a real visual approval."
};

Check(fixtureReview.Passes, "Complete fixture review should pass.");
foreach (var rejected in new[]
{
    fixtureReview with { StyleScore = 49, CharacterScore = 100, QualityScore = 100 },
    fixtureReview with { StyleScore = 69, CharacterScore = 69, QualityScore = 69 },
    fixtureReview with { QualityScore = 101 },
    fixtureReview with { ConsistentCharacter = false },
    fixtureReview with { FullHeadVisible = false },
    fixtureReview with { StyleComparison = "" },
    fixtureReview with { CharacterComparison = "" }
})
{
    Check(!rejected.Passes, "Style, identity, crop or missing comparison was accepted.");
}
Check((fixtureReview with { Approved = false, ReferenceColourAndLightMatch = false,
    PainterlyDetailMatches = false, CharacterFeaturesMatch = false, MatchesVisualStyle = false,
    Suggestions = ["Contour lines and different clothing shades"] }).Accepts(70),
    "Usable scored image was blocked by soft art-direction differences.");
Check(!fixtureReview.Accepts(80), "Configured threshold was ignored.");
Check((fixtureReview with { StyleScore = 70, CharacterScore = 70, QualityScore = 70 }).Accepts(70),
    "Exact acceptance boundary failed.");
Check(!(fixtureReview with { NoGeneratedText = false, StyleScore = 100, CharacterScore = 100,
    QualityScore = 100 }).Passes, "High score bypassed a hard defect.");
var incomplete = JsonNode.Parse(Data.Write(fixtureReview))!.AsObject();
incomplete.Remove(nameof(ImageReview.StyleScore));
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
