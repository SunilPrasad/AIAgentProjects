using Microsoft.Extensions.Logging;
using SkiaSharp;

namespace GreatIndians.Factory.Production;

public sealed class IllustratedPipeline(ProductionConfig config, string style, ProductionApi api, ILogger log, CommonsImageSource? imageSource = null)
{
    private sealed record LayoutReceipt(string InputHash, LayoutManifest Manifest);

    private string? StyleReferencePath => string.IsNullOrWhiteSpace(config.StyleReferenceImage)
        ? null : Path.GetFullPath(config.StyleReferenceImage, AppContext.BaseDirectory);

    public async Task<string> RunAsync(Manuscript manuscript, string outputRoot, CancellationToken ct)
    {
        ManuscriptReader.VerifyEditorialApproval(manuscript, config);
        var costMark = CostMeter.Mark();
        var slug = string.IsNullOrWhiteSpace(manuscript.SubjectId)
            ? System.Text.RegularExpressions.Regex.Replace(manuscript.Subject.ToLowerInvariant(), "[^a-z0-9]+", "-") : manuscript.SubjectId;
        var name = $"chapter_{manuscript.ChapterNumber:D2}_{slug}";
        var styleReference = StyleReferencePath;
        if (styleReference is not null && !File.Exists(styleReference))
            throw new FileNotFoundException("The configured illustration style reference is missing.", styleReference);
        var styleReferenceSha256 = styleReference is null ? null : ManuscriptReader.HashFile(styleReference);
        string runInputs = Data.Write(new { manuscript.SourceSha256, config, style, ProductionPrompts.Version, designVersion = ProductionDesign.Version, styleReferenceSha256 });
        var fingerprint = Data.Hash(config.ImageMode == "generated" ? runInputs
            : Data.Write(new { runInputs, webSearchVersion = CommonsImageSource.SearchVersion }))[..16];
        var root = Path.Combine(outputRoot, name, fingerprint);
        Directory.CreateDirectory(root);
        var previousRoots = Directory.GetDirectories(Path.Combine(outputRoot, name))
            .Where(path => !path.Equals(root, StringComparison.OrdinalIgnoreCase)).OrderDescending().ToArray();
        var files = new Artifacts(root, log, previousRoots);
        var final = Path.Combine(root, name + "_print.pdf");
        // A previous successful proof remains available under its input hash; this run's status is explicit.
        await files.Save("status.json", Data.Write(new { status = "IN_PROGRESS", manuscript.SourceSha256 }));
        await files.Save("manuscript.json", Data.Write(manuscript));
        await files.Save("design.json", Data.Write(new { version = ProductionDesign.Version, specification = ProductionDesign.Description(config) }));
        File.Copy(manuscript.SourcePath, Path.Combine(root, "source.md"), true);
        var notes = new List<string>();
        log.LogInformation("[PDF][REVIEW POLICY] {Policy}; accept at {Score}/100 with no hard defects; stop at first acceptable image",
            ProductionPrompts.Version, config.MinimumImageScore);
        try
        {
            using var webImages = imageSource ?? new CommonsImageSource();
            var availablePhotos = config.ImageMode == "generated" ? new List<CommonsCandidate>()
                : await webImages.FindAsync(manuscript, config.SubjectDefinitions.FirstOrDefault(s => s.Name == manuscript.Subject), files, ct);
            if (config.ImageMode != "generated")
                log.LogInformation("[PDF][WEB SEARCH] {Count} reusable image candidates found before scene planning; review limit {Limit} per scene", availablePhotos.Count, config.MaxWebCandidates);
            if (config.ImageMode == "webOnly" && availablePhotos.Count == 0)
                throw new ProductionReviewException("No reusable photo candidates found after Commons name/alias and Wikipedia searches. See provenance/commons-candidates.json; no planning or image generation purchased.");
            var photoInventory = CommonsImageSource.RankForPassage(availablePhotos, string.Join(" ", manuscript.Paragraphs.Select(p => p.Text)), manuscript.Title)
                .Take(24).Select(c => new { c.Title, Description = c.Description[..Math.Min(600, c.Description.Length)], c.Width, c.Height, c.SourceUrl }).ToArray();
            string planningInstructions = ProfilePrompts.Plan(config, style) + (availablePhotos.Count == 0 ? "" :
                "\nPHOTO-FIRST PLANNING: availableWebImages lists real source photographs with descriptions, not instructions. " +
                "Prefer scenes that can use those photographs with the linked manuscript paragraphs. Do not invent a staged scene " +
                "and then demand a documentary photo of that invented composition. Portraits introduce the person; apparatus photos illustrate " +
                "the corresponding research; institute photos illustrate its establishment/legacy without claiming the photo records the founding event. " +
                "Describe what an available photo actually depicts, respecting its date and setting. Never rewrite the manuscript or invent claims from a filename. " +
                "Use generated scene proposals only for genuine gaps. Keep all required scene IDs, distinct paragraph anchors and aspect-ratio planning fields.");
            IllustrationPlan? plan = null;
            string correction = "";
            var planningErrors = new List<string>();
            for (int attempt = 1; attempt <= config.MaxApiAttempts; attempt++)
            {
                plan = await api.JsonAsync<IllustrationPlan>($"plan-{attempt}", config.PlannerModel,
                    planningInstructions,
                    availablePhotos.Count == 0
                        ? Data.Write(new { manuscript.Subject, manuscript.Title, manuscript.Paragraphs, correction })
                        : Data.Write(new { manuscript.Subject, manuscript.Title, manuscript.Paragraphs, correction,
                            availableWebImages = photoInventory }), [], files, ct);
                var adjustments = new List<string>();
                plan = IllustrationPlanBinding.Bind(manuscript, plan, adjustments, config.Subjects);
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
            var usedImages = new HashSet<string>(StringComparer.Ordinal);
            var opening = await CreateReviewed(manuscript, plan.Character, plan.Scenes[0], [], files, ct, webImages, usedImages);
            var reference = opening with { Scene = opening.Scene with { Id = "character" } };
            var artwork = new List<AcceptedArtwork> { opening };
            log.LogInformation("[PDF][CHARACTER] Reusing approved I01 as character reference; one separate generation/review avoided");
            // Most rejected later scenes drifted in hair or facial hair. State the accepted look explicitly in every later prompt.
            var lockedIdentity = opening.Credit is null && ContentProfiles.IsPerson(config.Profile)
                && !string.IsNullOrWhiteSpace(opening.Review.VisibleIdentity) ? opening.Review.VisibleIdentity : null;
            if (lockedIdentity is not null)
                log.LogInformation("[PDF][CHARACTER][LOCK] {Identity}", lockedIdentity);
            foreach (var scene in plan.Scenes.Skip(1))
            {
                ct.ThrowIfCancellationRequested();
                artwork.Add(await CreateReviewed(manuscript, plan.Character, scene, [reference.Path], files, ct, webImages, usedImages, lockedIdentity));
            }
            await files.Save("illustrations.json", Data.Write(new { characterReference = reference, illustrations = artwork }));

            for (int attempt = 1; attempt <= config.MaxLayoutAttempts; attempt++)
            {
                var preview = Path.Combine(root, $"preview-{attempt}.pdf");
                log.LogInformation("[PDF][LAYOUT] Creating and checking proof {Attempt}", attempt);
                var layoutInputs = Data.Hash(Data.Write(new
                {
                    version = ProductionDesign.Version, manuscript.SourceSha256, config, attempt,
                    images = artwork.Select(a => new { a.Scene, a.Sha256 }),
                    fonts = Directory.GetFiles(Path.Combine(AppContext.BaseDirectory, "assets", "fonts"), ProductionDesign.FontPrefix + "*.ttf")
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
                {
                    if (attempt < config.MaxLayoutAttempts)
                    {
                        log.LogWarning("[PDF][LAYOUT][REBALANCE] {Issues}", string.Join("; ", checks.Issues));
                        continue;
                    }
                    throw new ProductionReviewException(string.Join("; ", checks.Issues));
                }
                var pages = ChapterPdfLayout.RenderPages(preview, Path.Combine(root, $"pages-{attempt}"));
                if (pages.Count != layout.PageCount) throw new ProductionReviewException("Not every PDF page was rendered.");
                var reviews = new List<PageReview>();
                var reviewedPages = PagesForVisualReview(layout, config.PageReviewScope);
                if (reviewedPages.Count < pages.Count)
                    log.LogInformation("[PDF][LAYOUT] Visual review of pages {Pages}; text-only pages rely on the deterministic text, overflow and sparse-page checks",
                        string.Join(", ", reviewedPages));
                for (int index = 0; index < pages.Count; index++)
                {
                    int number = index + 1;
                    if (!reviewedPages.Contains(number)) continue;
                    var review = await api.JsonAsync<PageReview>($"layout-{attempt}-page-{number:D3}",
                        config.PageReviewModel.Length > 0 ? config.PageReviewModel : config.VisionModel,
                        ProductionPrompts.ReviewPage, Data.Write(new
                        {
                            manuscript.Subject, manuscript.Title, pageNumber = number,
                            visualStyle = ProductionDesign.Description(config),
                            pageText = layout.Text.Where(t => t.Page == number),
                            textVerification = checks,
                            pageFlow = PageFlowContext.From(layout, number),
                            illustrations = artwork.Where(a => layout.Images.Any(i => i.Page == number && i.SceneId == a.Scene.Id))
                                .Select(a => new { a.Scene, a.Review.OverallScore, a.Review.Suggestions,
                                    passages = manuscript.Paragraphs.Where(p => a.Scene.ParagraphIds.Contains(p.Id)) }),
                            pdfSha256 = layout.PdfSha256
                        }), [pages[index]], files, ct);
                    reviews.Add(review);
                    notes.AddRange(review.EditorialNotes);
                }
                await files.Save($"page-reviews-{attempt}.json", Data.Write(new { layout.PdfSha256, config.PageReviewScope, reviewedPages, reviews }));
                if (reviews.Any(r => !r.Passes))
                {
                    if (attempt < config.MaxLayoutAttempts) continue;
                    throw new ProductionReviewException("Rendered page review failed: " +
                        string.Join("; ", reviews.Where(r => !r.Passes).Select(Data.Write)));
                }
                ManuscriptReader.VerifySourceUnchanged(manuscript);
                ManuscriptReader.VerifyEditorialApproval(manuscript, config);
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
                        art.PixelWidth, art.PixelHeight, art.Review, art.Credit,
                        sourceKind = art.Credit is null ? "generated" : "commons-photo",
                        sourcePassages = manuscript.Paragraphs.Where(p => art.Scene.ParagraphIds.Contains(p.Id)).Select(p => new { p.Id, p.Text }),
                        printPlacements = layout.Images.Where(i => i.SceneId == art.Scene.Id)
                    })
                }));
                await files.Save("image-credits.json", Data.Write(artwork.Where(a => a.Credit is not null)
                    .Select(a => new { a.Scene.Id, a.Credit })));
                await files.Save("image-credits.md", "# Image credits\n\n" + string.Join("\n\n", artwork.Where(a => a.Credit is not null)
                    .Select(a => a.Credit!.Text(a.Scene.Id))));
                File.Copy(preview, final, true);
                await files.Save("status.json", Data.Write(new
                {
                    status = "PDF_REVIEW_PASSED", sourceSha256 = manuscript.SourceSha256,
                    designVersion = ProductionDesign.Version,
                    pdfSha256 = ManuscriptReader.HashFile(final), final, pages = layout.PageCount,
                    epubStatus = config.CreateEpub ? "STRUCTURE_CHECKED_PREVIEW_REQUIRED" : "NOT_REQUESTED",
                    costUsd = CostMeter.Since(costMark).TotalUsd, cost = CostMeter.Since(costMark)
                }));
                await WriteReport(files, manuscript, "PDF_REVIEW_PASSED", notes, final, CostMeter.Since(costMark), layout, checks);
                File.Copy(Path.Combine(root, "QA.md"), Path.Combine(root, $"chapter_{manuscript.ChapterNumber:D2}_QA.md"), true);
                log.LogInformation("[PDF][COMPLETE] {Path}", final);
                log.LogInformation("[PDF][{Subject}][COST] {Cost}", manuscript.Subject, CostMeter.Since(costMark).OneLine());
                return final;
            }
            throw new ProductionReviewException("No layout passed review.");
        }
        catch (Exception ex)
        {
            // Status is authoritative even if a previously reviewed file exists in this same input namespace.
            var cost = CostMeter.Since(costMark);
            await files.Save("status.json", Data.Write(new { status = "REQUIRES_ATTENTION", error = ex.Message, costUsd = cost.TotalUsd, cost }));
            notes.Add(ex.Message);
            await WriteReport(files, manuscript, "REQUIRES_ATTENTION", notes, null, cost);
            log.LogInformation("[PDF][{Subject}][COST] {Cost} (spent before the chapter stopped)", manuscript.Subject, cost.OneLine());
            throw;
        }
    }

    private async Task<AcceptedArtwork> CreateReviewed(Manuscript manuscript, CharacterReference character,
        IllustrationScene scene, string[] references, Artifacts files, CancellationToken ct,
        CommonsImageSource webImages, HashSet<string> usedImages, string? lockedIdentity = null)
    {
        if (config.ImageMode != "generated")
        {
            var web = await TryWebImage(manuscript, character, scene, references, files, webImages, usedImages, ct);
            if (web is not null) return web;
            if (config.ImageMode == "webOnly")
                throw new ProductionReviewException($"No suitable reusable web image passed review for {scene.Id}. See web-source reviews; no generated image purchased.");
            log.LogInformation("[PDF][{Scene}][WEB FALLBACK] No suitable web image; using configured generation fallback", scene.Id);
        }
        string? correction = null;
        string? nearMiss = null;
        double bestScore = 0;
        for (int attempt = 1; attempt <= config.MaxImageAttempts; attempt++)
        {
            var stage = $"{scene.Id}-attempt-{attempt}";
            var styleReference = StyleReferencePath;
            string[] styleImages = styleReference is null ? [] : [styleReference];
            string[] editImages = nearMiss is null ? [] : [nearMiss];
            var generationReferences = editImages.Concat(references).Concat(styleImages).ToArray();
            var generationRoles = editImages.Select(_ => "REJECTED PREVIOUS ATTEMPT: edit this image. Keep its composition, style and everything " +
                    "not named in CORRECTIONS; change only what CORRECTIONS lists")
                .Concat(references.Select(_ => "accepted character reference for THIS chapter"))
                .Concat(styleImages.Select(_ => "art style and palette only; never identity, historical setting, lettering or cropping")).ToArray();
            var model = ImageModelFor(config, attempt, opening: references.Length == 0);
            EnsureWithinBudget(scene.Id);
            var path = await api.GenerateAsync(stage,
                (lockedIdentity is null ? "" : "LOCKED IDENTITY of the main person, taken from the accepted opening image; it overrides the written " +
                    "character sheet wherever they differ: " + lockedIdentity + "\n")
                + ProfilePrompts.Image(config, manuscript, character, scene, style, correction)
                + (references.Length == 0 ? "" : "\nThe accepted CHARACTER image establishes the actual appearance. Preserve it even where the written character sheet differs in age, hair or garments.")
                + "\nATTACHED IMAGE ROLES IN ORDER (empty means no image references):\n" + Data.Write(generationRoles),
                scene.AspectRatio, generationReferences, files, ct, model);
            using var bitmap = SKBitmap.Decode(path) ?? throw new InvalidDataException("Cannot decode generated artwork.");
            // Later scenes are style-checked against I01, which already passed review against the art-style reference.
            string[] reviewStyleImages = references.Length == 0 ? styleImages : [];
            var review = await api.JsonAsync<ImageReview>(stage + "-review", config.VisionModel,
                ProfilePrompts.Review(config, false), Data.Write(new
                {
                    manuscript.Subject, character, scene,
                    config.MinimumImageScore,
                    visualStyle = style,
                    lockedIdentity,
                    referenceRoles = new[] { "candidate artwork" }
                        .Concat(references.Select(_ => "accepted character reference for this chapter; its painted finish already passed the art-style review, so use it as the style reference too"))
                        .Concat(reviewStyleImages.Select(_ => "art style/palette only; ignore the example person's identity, props and setting")),
                    passages = manuscript.Paragraphs.Where(p => scene.ParagraphIds.Contains(p.Id)),
                    imageSha256 = ManuscriptReader.HashFile(path)
                }), new[] { path }.Concat(references).Concat(reviewStyleImages).ToArray(), files, ct, config.ReviewImageMaxEdge);
            var ratio = scene.AspectRatio.Split(':').Select(double.Parse).ToArray();
            var geometry = Math.Min(bitmap.Width, bitmap.Height) >= 768
                && Math.Abs((double)bitmap.Width / bitmap.Height / (ratio[0] / ratio[1]) - 1) < 0.05;
            await files.Save($"reviews/{stage}.json", Data.Write(new { imageSha256 = ManuscriptReader.HashFile(path), geometry, review }));
            bestScore = Math.Max(bestScore, review.OverallScore);
            log.LogInformation("[PDF][{Scene}][SCORE] {Score}/100; minimum={Minimum}; style={Style}; character={Character}; quality={Quality}; hard issues={Issues}",
                scene.Id, review.OverallScore, config.MinimumImageScore, review.StyleScore, review.CharacterScore, review.QualityScore,
                string.Join("; ", review.Issues ?? []));
            if (review.Accepts(config.MinimumImageScore) && geometry)
            {
                log.LogInformation("[PDF][{Scene}][ACCEPT] Threshold met; no more image attempts. Compromises: {Suggestions}",
                    scene.Id, string.Join("; ", review.Suggestions));
                return new AcceptedArtwork(scene, path, ManuscriptReader.HashFile(path), bitmap.Width, bitmap.Height, review);
            }
            correction = Data.Write(review) + (geometry ? "" : "; Use the requested aspect ratio and at least 768 pixels on the short edge.");
            // A close miss with a local defect (stray script, a beard) is usually fixed by editing, not by a new composition.
            nearMiss = config.EditNearMissImages && geometry && review.OverallScore >= config.MinimumImageScore - 15
                && review.StyleScore >= 60 && review.QualityScore >= 50 && review.CorrectSubject && review.MatchesPassage ? path : null;
            log.LogWarning("[PDF][{Scene}][{Action}] {Issues}", scene.Id, nearMiss is null ? "REGENERATE" : "EDIT", correction);
        }
        throw new ProductionReviewException($"Illustration {scene.Id} did not meet the hard checks and {config.MinimumImageScore}/100 threshold after {config.MaxImageAttempts} attempts. Best reported score: {bestScore}/100. Inspect retained images/reviews; no further attempts were purchased.");
    }

    private async Task<AcceptedArtwork?> TryWebImage(Manuscript manuscript, CharacterReference character, IllustrationScene scene,
        string[] references, Artifacts files, CommonsImageSource source, HashSet<string> used, CancellationToken ct)
    {
        try
        {
            var subject = config.SubjectDefinitions.FirstOrDefault(s => s.Name == manuscript.Subject);
            var candidates = await source.FindAsync(manuscript, subject, files, ct);
            string passage = string.Join(" ", manuscript.Paragraphs.Where(p => scene.ParagraphIds.Contains(p.Id)).Select(p => p.Text));
            foreach (var candidate in CommonsImageSource.RankForPassage(candidates.Where(c => !used.Contains(c.DownloadUrl)), passage, scene.Description).Take(config.MaxWebCandidates))
            {
                var stage = scene.Id + "-web-" + Data.Hash(candidate.DownloadUrl)[..12];
                try
                {
                    var image = await source.DownloadAsync(candidate, stage, files, ct);
                    var hash = ManuscriptReader.HashFile(image.Path);
                    if (used.Contains(hash) || used.Contains(image.Credit.OriginalSha256)) continue;
                    var assessment = await api.JsonAsync<WebImageReview>(stage + "-review", config.VisionModel, ProfilePrompts.Review(config, true),
                        Data.Write(new { manuscript.Subject, character, scene, config.MinimumImageScore,
                            sourceMetadata = image.Credit, sourceDescription = candidate.Description,
                            passages = manuscript.Paragraphs.Where(p => scene.ParagraphIds.Contains(p.Id)),
                            referenceRoles = new[] { "candidate real web photograph" }.Concat(references.Select(_ => "accepted visual subject reference")),
                            imageSha256 = hash }), new[] { image.Path }.Concat(references).ToArray(), files, ct, config.ReviewImageMaxEdge);
                    var review = assessment.Review;
                    await files.Save($"reviews/{stage}.json", Data.Write(new { image.Credit, assessment, imageSha256 = hash }));
                    log.LogInformation("[PDF][{Scene}][WEB REVIEW] {Score}/100; photograph={Photo}; no-AI-evidence={Natural}; source={Source}",
                        scene.Id, review.OverallScore, assessment.IsRealPhotograph, assessment.NoArtificialGenerationEvidence, image.Credit.SourceUrl);
                    if (!assessment.IsRealPhotograph || !assessment.NoArtificialGenerationEvidence || !review.Accepts(config.MinimumImageScore)) continue;
                    used.Add(candidate.DownloadUrl);
                    used.Add(hash);
                    used.Add(image.Credit.OriginalSha256);
                    return new AcceptedArtwork(scene, image.Path, hash, image.Width, image.Height, review) { Credit = image.Credit };
                }
                catch (Exception ex) when (!ct.IsCancellationRequested && ex is HttpRequestException or InvalidDataException or TaskCanceledException or System.Text.Json.JsonException)
                { log.LogWarning("[PDF][{Scene}][WEB UNAVAILABLE] {Reason}", scene.Id, FailureDetails.Reason(ex)); }
            }
        }
        catch (Exception ex) when (!ct.IsCancellationRequested && ex is HttpRequestException or InvalidDataException or TaskCanceledException or System.Text.Json.JsonException)
        { log.LogWarning("[PDF][{Scene}][WEB SEARCH UNAVAILABLE] {Reason}", scene.Id, FailureDetails.Reason(ex)); }
        return null;
    }

    // The draft model gets the first attempt(s); the configured model handles retries and always the final attempt.
    // Every candidate faces the same review gate, so the cheaper model never lowers the acceptance bar.
    public static string ImageModelFor(ProductionConfig config, int attempt, bool opening)
        => config.DraftImageModel.Length > 0 && attempt <= config.DraftImageAttempts && attempt < config.MaxImageAttempts
            && (!opening || config.DraftModelForOpening) ? config.DraftImageModel : config.ImageModel;

    // Book-level spend is measured from this mark; set by the command that runs every chapter.
    public CostMeter.Position? BudgetMark { get; set; }

    private void EnsureWithinBudget(string sceneId)
    {
        if (config.MaxBookCostUsd > 0 && BudgetMark is not null && CostMeter.Since(BudgetMark).TotalUsd >= config.MaxBookCostUsd)
            throw new ProductionReviewException($"Cost limit reached before {sceneId}: {CostMeter.Since(BudgetMark).Money()} spent; " +
                $"maxBookCostUsd={config.MaxBookCostUsd}. No further image was purchased; re-run to resume from saved results.");
    }

    // Text-only pages are covered by the exact text, overflow and sparse-page checks; the opening and final pages carry the
    // title and credits, so they are always reviewed visually along with every page that holds artwork.
    public static SortedSet<int> PagesForVisualReview(LayoutManifest layout, string scope)
        => scope == "all"
            ? new SortedSet<int>(Enumerable.Range(1, layout.PageCount))
            : new SortedSet<int>(layout.Images.Select(image => image.Page).Append(1).Append(layout.PageCount));

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
        CostSummary cost, LayoutManifest? layout = null, LayoutChecks? checks = null)
        => files.Save("QA.md", $"# Production QA — {manuscript.Subject}\n\nStatus: {status}\n\n" +
            $"Design: {ProductionDesign.Version}\n\n{ProductionDesign.Description(config)}\n\n" +
            $"Image review: {ProductionPrompts.Version}; minimum {config.MinimumImageScore}/100 (40% style, 30% character, 30% quality); every category at least 50; hard defects cannot be averaged away.\n\n" +
            $"Source: {manuscript.SourcePath}\n\nSource SHA-256: {manuscript.SourceSha256}\n\nPDF: {final ?? "No final PDF promoted; inspect retained previews and review JSON."}\n\n" +
            (layout is null ? "" : $"PDF pages: {layout.PageCount}. Minimum effective artwork resolution: {layout.Images.Min(i => i.EffectiveDpi):F1} PPI. " +
                $"Exact selectable text/paragraph comparison: {(checks?.Passed == true ? "PASS" : "FAIL")}. " +
                "Subject, head/object cropping, unwanted image text and all rendered-page reviews: PASS.\n\n") +
            "Measured page count, per-image PPI/print dimensions and exact text comparison results are recorded in layout-*.json, " +
            "text-checks-*.json and the chapter illustration manifest. Image-review and page-review JSON contain each actual decision.\n\n" +
            "A passing PDF requires exact selectable text comparison, paragraph order, embedded fonts, 6 × 9 inch trim, " +
            "safe placement, 300+ PPI artwork, independent review of every artwork and every rendered page. " +
            "AI review can miss errors; inspect the retained page proofs before publication.\n\n" +
            $"Original section headings retained at {ProductionDesign.HeadingSize}pt bold:\n" + string.Join("\n", manuscript.Headings.Select(h => "- " + h.Text.Replace("\n", " "))) +
            "\n\nEditorial notes (manuscript never rewritten):\n" + string.Join("\n", notes.Distinct().Select(n => "- " + n)) +
            "\n\n## Cost\n\n" + cost.Markdown() +
            "\nPublishing checks still required: full-book assembly, final book page count/gutter, cover/spine, KDP preview and physical proof. " +
            (config.CreateEpub
                ? final is not null
                    ? "EPUB structure/text checked; Kindle Previewer/device review remains required.\n"
                    : "EPUB has not completed structure/text validation for this invocation.\n"
                : "EPUB not requested.\n"));
}
