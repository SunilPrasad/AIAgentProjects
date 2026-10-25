using Microsoft.Extensions.Logging;
using SkiaSharp;

namespace GreatIndians.Factory.Production;

public sealed class IllustratedPipeline(ProductionConfig config, string style, ProductionApi api, ILogger log)
{
    private sealed record LayoutReceipt(string InputHash, LayoutManifest Manifest);

    private string? StyleReferencePath => string.IsNullOrWhiteSpace(config.StyleReferenceImage)
        ? null : Path.GetFullPath(config.StyleReferenceImage, AppContext.BaseDirectory);

    public async Task<string> RunAsync(Manuscript manuscript, string outputRoot, CancellationToken ct)
    {
        var slug = System.Text.RegularExpressions.Regex.Replace(manuscript.Subject.ToLowerInvariant(), "[^a-z0-9]+", "-");
        var name = $"chapter_{manuscript.ChapterNumber:D2}_{slug}";
        var styleReference = StyleReferencePath;
        if (styleReference is not null && !File.Exists(styleReference))
            throw new FileNotFoundException("The configured illustration style reference is missing.", styleReference);
        var styleReferenceSha256 = styleReference is null ? null : ManuscriptReader.HashFile(styleReference);
        var fingerprint = Data.Hash(Data.Write(new { manuscript.SourceSha256, config, style, ProductionPrompts.Version, styleReferenceSha256 }))[..16];
        var root = Path.Combine(outputRoot, name, fingerprint);
        Directory.CreateDirectory(root);
        var previousRoots = Directory.GetDirectories(Path.Combine(outputRoot, name))
            .Where(path => !path.Equals(root, StringComparison.OrdinalIgnoreCase)).OrderDescending().ToArray();
        var files = new Artifacts(root, log, previousRoots);
        var final = Path.Combine(root, name + "_print.pdf");
        // A previous successful proof remains available under its input hash; this run's status is explicit.
        await files.Save("status.json", Data.Write(new { status = "IN_PROGRESS", manuscript.SourceSha256 }));
        await files.Save("manuscript.json", Data.Write(manuscript));
        File.Copy(manuscript.SourcePath, Path.Combine(root, "source.md"), true);
        var notes = new List<string>();
        try
        {
            IllustrationPlan? plan = null;
            string correction = "";
            var planningErrors = new List<string>();
            for (int attempt = 1; attempt <= config.MaxApiAttempts; attempt++)
            {
                plan = await api.JsonAsync<IllustrationPlan>($"plan-{attempt}", config.PlannerModel,
                    ProductionPrompts.Plan(style, config.IllustrationCount),
                    Data.Write(new { manuscript.Subject, manuscript.Title, manuscript.Paragraphs, correction }), [], files, ct);
                var adjustments = new List<string>();
                plan = IllustrationPlanBinding.Bind(manuscript, plan, adjustments);
                var errors = ValidatePlan(manuscript, plan, config.IllustrationCount);
                await files.Save($"reviews/plan-{attempt}-validation.json", Data.Write(new { adjustments, errors, boundPlan = plan }));
                foreach (var adjustment in adjustments)
                    log.LogInformation("[PDF][plan-{Attempt}][BIND] {Adjustment}", attempt, adjustment);
                if (errors.Count == 0) break;
                correction = string.Join("; ", errors);
                planningErrors = errors;
                log.LogWarning("[PDF][plan-{Attempt}][INVALID] {Reasons}", attempt, correction);
                plan = null;
            }
            if (plan is null) throw new ProductionReviewException("Illustration plan did not pass validation: " + string.Join("; ", planningErrors));
            notes.AddRange(plan.EditorialNotes);
            await files.Save("illustration-plan.json", Data.Write(plan));

            // The accepted opening artwork is also the character reference: no duplicate paid portrait.
            var opening = await CreateReviewed(manuscript, plan.Character, plan.Scenes[0], [], files, ct);
            var reference = opening with { Scene = opening.Scene with { Id = "character" } };
            var artwork = new List<AcceptedArtwork> { opening };
            log.LogInformation("[PDF][CHARACTER] Reusing approved I01 as character reference; one separate generation/review avoided");
            foreach (var scene in plan.Scenes.Skip(1))
            {
                ct.ThrowIfCancellationRequested();
                artwork.Add(await CreateReviewed(manuscript, plan.Character, scene, [reference.Path], files, ct));
            }
            await files.Save("illustrations.json", Data.Write(new { characterReference = reference, illustrations = artwork }));

            for (int attempt = 1; attempt <= config.MaxLayoutAttempts; attempt++)
            {
                var preview = Path.Combine(root, $"preview-{attempt}.pdf");
                log.LogInformation("[PDF][LAYOUT] Creating and checking proof {Attempt}", attempt);
                var layoutInputs = Data.Hash(Data.Write(new
                {
                    version = "reference-layout-v2", manuscript.SourceSha256, config, attempt,
                    images = artwork.Select(a => new { a.Scene, a.Sha256 }),
                    fonts = Directory.GetFiles(Path.Combine(AppContext.BaseDirectory, "assets", "fonts"), "DejaVuSerif-*.ttf")
                        .Order().Select(ManuscriptReader.HashFile).ToArray()
                }));
                var receiptPath = Path.Combine(root, "cache", $"layout-{attempt}.json");
                LayoutManifest? layout = null;
                if (File.Exists(receiptPath) && File.Exists(preview))
                {
                    try
                    {
                        var receipt = Data.Read<LayoutReceipt>(await File.ReadAllTextAsync(receiptPath, ct));
                        if (receipt.InputHash == layoutInputs && receipt.Manifest.PdfSha256 == ManuscriptReader.HashFile(preview))
                            layout = receipt.Manifest;
                    }
                    catch (System.Text.Json.JsonException) { }
                }
                layout ??= ChapterPdfLayout.Create(manuscript, artwork, config, preview, attempt == 1 ? 1 : 0.85);
                await files.Save($"cache/layout-{attempt}.json", Data.Write(new LayoutReceipt(layoutInputs, layout)));
                await files.Save($"layout-{attempt}.json", Data.Write(layout));
                var checks = ChapterPdfLayout.Verify(preview, manuscript, layout, config);
                await files.Save($"text-checks-{attempt}.json", Data.Write(checks));
                if (!checks.Passed)
                    throw new ProductionReviewException(string.Join("; ", checks.Issues));
                var pages = ChapterPdfLayout.RenderPages(preview, Path.Combine(root, $"pages-{attempt}"));
                if (pages.Count != layout.PageCount) throw new ProductionReviewException("Not every PDF page was rendered.");
                var reviews = new List<PageReview>();
                for (int index = 0; index < pages.Count; index++)
                {
                    int number = index + 1;
                    var review = await api.JsonAsync<PageReview>($"layout-{attempt}-page-{number:D3}", config.VisionModel,
                        ProductionPrompts.ReviewPage, Data.Write(new
                        {
                            manuscript.Subject, manuscript.Title, pageNumber = number,
                            visualStyle = $"Ages 8–12. DejaVu Serif; {config.FontSize}pt body / {config.FontSize * config.LineSpacing}pt leading; centred royal-blue 21.5pt main title; cream #FFFDF7 paper; thin gold top rule; blue page numbers. Artwork: bright warm painterly storybook style, complete heads and no image lettering.",
                            pageText = layout.Text.Where(t => t.Page == number),
                            illustrations = artwork.Where(a => layout.Images.Any(i => i.Page == number && i.SceneId == a.Scene.Id))
                                .Select(a => new { a.Scene, passages = manuscript.Paragraphs.Where(p => a.Scene.ParagraphIds.Contains(p.Id)) }),
                            pdfSha256 = layout.PdfSha256
                        }), [pages[index]], files, ct);
                    reviews.Add(review);
                    notes.AddRange(review.EditorialNotes);
                }
                await files.Save($"page-reviews-{attempt}.json", Data.Write(new { layout.PdfSha256, reviews }));
                if (reviews.Any(r => !r.Passes))
                {
                    if (attempt < config.MaxLayoutAttempts) continue;
                    throw new ProductionReviewException("Rendered page review failed: " +
                        string.Join("; ", reviews.Where(r => !r.Passes).Select(Data.Write)));
                }
                ManuscriptReader.VerifySourceUnchanged(manuscript);
                if (artwork.Append(reference).Any(a => ManuscriptReader.HashFile(a.Path) != a.Sha256))
                    throw new ProductionReviewException("Reviewed artwork changed before finalisation.");
                if (styleReference is not null && ManuscriptReader.HashFile(styleReference) != styleReferenceSha256)
                    throw new ProductionReviewException("Illustration style reference changed during production.");
                if (!ChapterPdfLayout.Verify(preview, manuscript, layout, config).Passed)
                    throw new ProductionReviewException("Final PDF verification failed.");
                if (config.CreateEpub) ChapterEpub.Create(manuscript, artwork, config, Path.Combine(root, name + ".epub"));
                var deliveredArt = Path.Combine(root, $"chapter_{manuscript.ChapterNumber:D2}_artwork");
                Directory.CreateDirectory(deliveredArt);
                foreach (var art in artwork.Append(reference))
                    File.Copy(art.Path, Path.Combine(deliveredArt, art.Scene.Id + ".png"), true);
                await files.Save($"chapter_{manuscript.ChapterNumber:D2}_illustrations.json", Data.Write(new
                {
                    manuscript.Subject, manuscript.SourceSha256, layout.PdfSha256,
                    character = plan.Character, characterReview = reference.Review,
                    characterReferenceReuses = "I01", styleReferenceSha256,
                    illustrations = artwork.Select(art => new
                    {
                        art.Scene, filename = Path.Combine(deliveredArt, art.Scene.Id + ".png"), art.Sha256,
                        art.PixelWidth, art.PixelHeight, art.Review,
                        sourcePassages = manuscript.Paragraphs.Where(p => art.Scene.ParagraphIds.Contains(p.Id)).Select(p => new { p.Id, p.Text }),
                        printPlacements = layout.Images.Where(i => i.SceneId == art.Scene.Id)
                    })
                }));
                File.Copy(preview, final, true);
                await files.Save("status.json", Data.Write(new
                {
                    status = "PDF_REVIEW_PASSED", sourceSha256 = manuscript.SourceSha256,
                    pdfSha256 = ManuscriptReader.HashFile(final), final, pages = layout.PageCount,
                    epubStatus = config.CreateEpub ? "STRUCTURE_CHECKED_PREVIEW_REQUIRED" : "NOT_REQUESTED"
                }));
                await WriteReport(files, manuscript, "PDF_REVIEW_PASSED", notes, final, layout, checks);
                File.Copy(Path.Combine(root, "QA.md"), Path.Combine(root, $"chapter_{manuscript.ChapterNumber:D2}_QA.md"), true);
                log.LogInformation("[PDF][COMPLETE] {Path}", final);
                return final;
            }
            throw new ProductionReviewException("No layout passed review.");
        }
        catch (Exception ex)
        {
            // Status is authoritative even if a previously reviewed file exists in this same input namespace.
            await files.Save("status.json", Data.Write(new { status = "REQUIRES_ATTENTION", error = ex.Message }));
            notes.Add(ex.Message);
            await WriteReport(files, manuscript, "REQUIRES_ATTENTION", notes, null);
            throw;
        }
    }

    private async Task<AcceptedArtwork> CreateReviewed(Manuscript manuscript, CharacterReference character,
        IllustrationScene scene, string[] references, Artifacts files, CancellationToken ct)
    {
        string? correction = null;
        for (int attempt = 1; attempt <= config.MaxImageAttempts; attempt++)
        {
            var stage = $"{scene.Id}-attempt-{attempt}";
            var styleReference = StyleReferencePath;
            string[] styleImages = styleReference is null ? [] : [styleReference];
            var generationReferences = references.Concat(styleImages).ToArray();
            var generationRoles = references.Select(_ => "accepted character reference for THIS chapter")
                .Concat(styleImages.Select(_ => "art style and palette only; never identity, historical setting, lettering or cropping")).ToArray();
            var path = await api.GenerateAsync(stage, ProductionPrompts.Image(manuscript, character, scene, style, correction)
                + "\nATTACHED IMAGE ROLES IN ORDER (empty means no image references):\n" + Data.Write(generationRoles),
                scene.AspectRatio, generationReferences, files, ct);
            using var bitmap = SKBitmap.Decode(path) ?? throw new InvalidDataException("Cannot decode generated artwork.");
            var review = await api.JsonAsync<ImageReview>(stage + "-review", config.VisionModel,
                ProductionPrompts.ReviewImage, Data.Write(new
                {
                    manuscript.Subject, character, scene,
                    visualStyle = style,
                    referenceRoles = new[] { "candidate artwork" }
                        .Concat(references.Select(_ => "accepted character reference for this chapter"))
                        .Concat(styleImages.Select(_ => "art style/palette only; ignore the example person's identity, props and setting")),
                    passages = manuscript.Paragraphs.Where(p => scene.ParagraphIds.Contains(p.Id)),
                    imageSha256 = ManuscriptReader.HashFile(path)
                }), new[] { path }.Concat(generationReferences).ToArray(), files, ct);
            var ratio = scene.AspectRatio.Split(':').Select(double.Parse).ToArray();
            var geometry = Math.Min(bitmap.Width, bitmap.Height) >= 768
                && Math.Abs((double)bitmap.Width / bitmap.Height / (ratio[0] / ratio[1]) - 1) < 0.05;
            await files.Save($"reviews/{stage}.json", Data.Write(new { imageSha256 = ManuscriptReader.HashFile(path), geometry, review }));
            if (review.Passes && geometry)
                return new AcceptedArtwork(scene, path, ManuscriptReader.HashFile(path), bitmap.Width, bitmap.Height, review);
            correction = Data.Write(review) + (geometry ? "" : "; Use the requested aspect ratio and at least 768 pixels on the short edge.");
            log.LogWarning("[PDF][{Scene}][REGENERATE] {Issues}", scene.Id, correction);
        }
        throw new ProductionReviewException($"Illustration {scene.Id} did not pass review after {config.MaxImageAttempts} attempts.");
    }

    public static List<string> ValidatePlan(Manuscript manuscript, IllustrationPlan plan, int count)
    {
        var errors = new List<string>();
        if (plan.Character is null || plan.Character.Name != manuscript.Subject) errors.Add("Character name must match the exact subject.");
        if (plan.Character is not null && new[] { plan.Character.Period, plan.Character.Region, plan.Character.Role,
            plan.Character.Clothing, plan.Character.HairAndHeadwear, plan.Character.Appearance, plan.Character.Environment }.Any(string.IsNullOrWhiteSpace))
            errors.Add("Complete all character reference fields.");
        if (plan.Character is not null && (plan.Character.Objects is null || plan.Character.Avoid is null))
            errors.Add("Include character objects and avoid lists.");
        if (plan.EditorialNotes is null || plan.Scenes is null || plan.Scenes.Count != count)
        { errors.Add($"Provide exactly {count} scenes and editorialNotes."); return errors; }
        int previous = -1;
        for (int i = 0; i < plan.Scenes.Count; i++)
        {
            var scene = plan.Scenes[i];
            int anchor = manuscript.Paragraphs.FindIndex(p => p.Id == scene.InsertBeforeParagraphId);
            var prefix = $"Scene I{i + 1:D2}: ";
            if (scene.Id != $"I{i + 1:D2}") errors.Add(prefix + "incorrect scene ID.");
            if (scene.Subject != manuscript.Subject) errors.Add(prefix + $"subject must be {manuscript.Subject}.");
            if (scene.ParagraphIds is not { Count: > 0 }) errors.Add(prefix + "at least one retained source paragraph is required.");
            else
            {
                foreach (var id in scene.ParagraphIds.Where(id => !manuscript.Paragraphs.Any(p => p.Id == id)))
                    errors.Add(prefix + $"unknown source paragraph {id}.");
                if (!scene.ParagraphIds.Contains(scene.InsertBeforeParagraphId))
                    errors.Add(prefix + "placement must be one of the scene's retained source paragraphs.");
            }
            if (anchor < 0) errors.Add(prefix + $"unknown placement paragraph '{scene.InsertBeforeParagraphId}'.");
            else if (anchor <= previous) errors.Add(prefix + "placement must follow the preceding scene.");
            if (string.IsNullOrWhiteSpace(scene.Description) || string.IsNullOrWhiteSpace(scene.AccuracyRequirements)
                || string.IsNullOrWhiteSpace(scene.AltText) || scene.NegativeConstraints is null)
                errors.Add(prefix + "description, accuracy requirements, alt text and negative constraints are required.");
            if (!(i == 0 ? scene.AspectRatio == "3:2" && anchor == 0 : new[] { "16:9", "3:2", "4:3", "1:1" }.Contains(scene.AspectRatio)))
                errors.Add(prefix + "opening must use 3:2 at P001; later scenes must use 16:9, 3:2, 4:3 or 1:1.");
            previous = anchor;
        }
        return errors;
    }

    private Task WriteReport(Artifacts files, Manuscript manuscript, string status, List<string> notes, string? final,
        LayoutManifest? layout = null, LayoutChecks? checks = null)
        => files.Save("QA.md", $"# Production QA — {manuscript.Subject}\n\nStatus: {status}\n\n" +
            $"Source: {manuscript.SourcePath}\n\nSource SHA-256: {manuscript.SourceSha256}\n\nPDF: {final ?? "No final PDF promoted; inspect retained previews and review JSON."}\n\n" +
            (layout is null ? "" : $"PDF pages: {layout.PageCount}. Minimum effective artwork resolution: {layout.Images.Min(i => i.EffectiveDpi):F1} PPI. " +
                $"Exact selectable text/paragraph comparison: {(checks?.Passed == true ? "PASS" : "FAIL")}. " +
                "Subject, head/object cropping, unwanted image text and all rendered-page reviews: PASS.\n\n") +
            "Measured page count, per-image PPI/print dimensions and exact text comparison results are recorded in layout-*.json, " +
            "text-checks-*.json and the chapter illustration manifest. Image-review and page-review JSON contain each actual decision.\n\n" +
            "A passing PDF requires exact selectable text comparison, paragraph order, embedded fonts, 6 × 9 inch trim, " +
            "safe placement, 300+ PPI artwork, independent review of every artwork and every rendered page. " +
            "AI review can miss errors; inspect the retained page proofs before publication.\n\n" +
            "Secondary headings suppressed in the layout only:\n" + string.Join("\n", manuscript.SuppressedHeadings.Select(h => "- " + h.Replace("\n", " "))) +
            "\n\nEditorial notes (manuscript never rewritten):\n" + string.Join("\n", notes.Distinct().Select(n => "- " + n)) +
            "\n\nPublishing checks still required: full-book assembly, final book page count/gutter, cover/spine, KDP preview and physical proof. " +
            (config.CreateEpub
                ? final is not null
                    ? "EPUB structure/text checked; Kindle Previewer/device review remains required.\n"
                    : "EPUB has not completed structure/text validation for this invocation.\n"
                : "EPUB not requested.\n"));
}
