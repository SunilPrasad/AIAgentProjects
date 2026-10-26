using GreatIndians.Factory;
using GreatIndians.Factory.Production;
using SkiaSharp;

// Reproduce layout failures against retained reviewed inputs, with zero model/network calls.
internal static class SavedLayoutSmokeTest
{
    private sealed record Receipt(WebImageCredit Credit, WebImageReview assessment, string imageSha256);
    public static void Run(string bookPath, string runRoot)
    {
        bookPath = Path.GetFullPath(bookPath);
        runRoot = Path.GetFullPath(runRoot);
        var config = BookDefinition.Load(bookPath).ForProduction(bookPath);
        var saved = Data.Read<Manuscript>(File.ReadAllText(Path.Combine(runRoot, "manuscript.json")));
        var manuscript = ManuscriptReader.Load(saved.SourcePath, config);
        if (manuscript.SourceSha256 != saved.SourceSha256) throw new Exception("Saved manuscript changed; select a matching run for layout reproduction.");
        var plan = Data.Read<IllustrationPlan>(File.ReadAllText(Path.Combine(runRoot, "illustration-plan.json")));
        var artwork = new List<AcceptedArtwork>();
        foreach (var scene in plan.Scenes)
        {
            foreach (var reviewFile in Directory.GetFiles(Path.Combine(runRoot, "reviews"), scene.Id + "-web-*.json")
                .Where(p => !p.EndsWith("-candidate-order.json", StringComparison.Ordinal)))
            {
                var review = Data.Read<Receipt>(File.ReadAllText(reviewFile));
                if (!review.assessment.IsRealPhotograph || !review.assessment.NoArtificialGenerationEvidence
                    || !review.assessment.Review.Accepts(config.MinimumImageScore)) continue;
                string image = Path.Combine(runRoot, "artwork", Path.GetFileNameWithoutExtension(reviewFile) + ".png");
                if (ManuscriptReader.HashFile(image) != review.imageSha256) throw new Exception("Saved photograph hash changed.");
                using var bitmap = SKBitmap.Decode(image) ?? throw new Exception("Saved image could not be decoded.");
                artwork.Add(new AcceptedArtwork(scene, image, review.imageSha256, bitmap.Width, bitmap.Height, review.assessment.Review) { Credit = review.Credit });
                break;
            }
            if (!artwork.Any(a => a.Scene.Id == scene.Id)) throw new Exception("No approved saved photograph for " + scene.Id);
        }
        string proofRoot = Path.Combine(runRoot, "offline-layout-proof");
        string pdfPath = Path.Combine(proofRoot, "chapter-layout-review.pdf");
        var layout = ChapterPdfLayout.Create(manuscript, artwork, config, pdfPath);
        var checks = ChapterPdfLayout.Verify(pdfPath, manuscript, layout, config);
        if (!checks.Passed) throw new Exception(string.Join("; ", checks.Issues));
        File.WriteAllText(Path.Combine(proofRoot, "layout.json"), Data.Write(layout));
        File.WriteAllText(Path.Combine(proofRoot, "text-checks.json"), Data.Write(checks));
        var pages = ChapterPdfLayout.RenderPages(pdfPath, Path.Combine(proofRoot, "pages"));
        Console.WriteLine($"PASS actual saved chapter layout: {artwork.Count} approved photos, {pages.Count} rendered pages, exact text/fonts/credits/safety. Proof only; no production approval or model calls: {pdfPath}");
    }
}
