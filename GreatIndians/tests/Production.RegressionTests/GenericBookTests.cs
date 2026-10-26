using System.Net;
using System.Text;
using System.Text.Json;
using System.Xml.Linq;
using System.IO.Compression;
using GreatIndians.Factory;
using GreatIndians.Factory.Production;
using Microsoft.Extensions.Logging.Abstractions;
using SkiaSharp;

internal static class GenericBookTests
{
    private const string LongCreditUrl = "https://collections.example.org/document/historical-scientist-archive-record/617a7a44cf8b8968b33830eb?filter=Personnalit%C3%A9&category=Images%20fixes&sort=dateDePriseDeVue&position=1935&page=127";
    public static async Task RunAsync(string root)
    {
        var books = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../books"));
        var outputs = new List<string>();
        foreach (var path in Directory.GetFiles(books, "*.json"))
        {
            var definition = BookDefinition.Load(path);
            var writing = definition.ForWriting(path);
            var production = definition.ForProduction(path);
            writing.Validate(); production.Validate();
            Check(writing.Personalities.Count == 10 && production.SubjectDefinitions.Length == 10, "Missing configured subjects.");
            Check(File.Exists(writing.StyleBible) && File.Exists(production.IllustrationStyle)
                && File.Exists(production.StyleReferenceImage), "Config assets did not resolve relative to its definition.");
            Check(production.RequireEditorialApproval, "New books should require matching editorial approval.");
            outputs.Add(writing.OutputDirectory);
        }
        Check(outputs.Count == 4 && outputs.Distinct().Count() == 4, "Book outputs overlap.");

        var subject = new SubjectDefinition { Id = "temple-alpha", Name = "Temple Alpha", Aliases = ["Alpha Shrine"] };
        var definitionOne = new BookDefinition { Id = "test-book", Title = "Any topic", Profile = "temple", Subjects = [subject] };
        definitionOne.Validate();
        bool unsafeRejected = false;
        try { (definitionOne with { Id = "../escape" }).Validate(); }
        catch (InvalidDataException) { unsafeRejected = true; }
        Check(unsafeRejected, "Unsafe book ID accepted.");
        var minimal = definitionOne.ForWriting(Path.Combine(root, "definition.json"));
        Check(File.Exists(minimal.StyleBible), "Minimal definition did not resolve bundled common style.");

        var config = new ProductionConfig
        {
            BookId = "test-book", BookTitle = "Any topic", Profile = "temple", Subjects = [subject.Name],
            SubjectDefinitions = [subject], IllustrationCount = 1, StyleReferenceImage = "", ImageMode = "webOnly",
            Author = "Fixture Author", CreateEpub = true
        };
        config.Validate();
        var manuscriptRoot = Path.Combine(root, "generic-book", "final-chapters");
        Directory.CreateDirectory(manuscriptRoot);
        var markdown = Path.Combine(manuscriptRoot, "01-temple-alpha.md");
        File.WriteAllText(markdown, "# A place worth understanding\n\n" + string.Join("\n\n", Enumerable.Range(1, 4)
            .Select(i => $"Paragraph {i} is an offline layout fixture, not a historical claim. " +
                "The complete text must be retained exactly while a photograph is placed at a supported narrative break. " +
                "The subject is a place, so the planner must not require a person's hair, clothing or childhood. " +
                "Image credits are separate from the original narrative and do not change its words.")));
        var manuscript = ManuscriptReader.Load(markdown, config);
        Check(manuscript.SubjectId == subject.Id && manuscript.Subject == subject.Name, "Stable filename mapping failed without a subject in the title.");
        var aliasPath = Path.Combine(manuscriptRoot, "alias.md");
        File.WriteAllText(aliasPath, File.ReadAllText(markdown).Replace("A place worth understanding", "Alpha Shrine"));
        Check(ManuscriptReader.Load(aliasPath, config).SubjectId == subject.Id, "Configured title alias was not recognised.");
        Check(ProfilePrompts.Plan(config, "style").Contains("No main person is required"), "Place plan still requires a portrait.");
        Check(new PromptSet(minimal, "style").Writer.Contains("temple"), "Temple profile missing from writer.");
        var plan = Plan(manuscript);
        var wrong = plan with { Scenes = [plan.Scenes[0] with { Subject = "Temple Beta" }] };
        var bound = IllustrationPlanBinding.Bind(manuscript, wrong, [], ["Temple Alpha", "Temple Beta"]);
        Check(IllustratedPipeline.ValidatePlan(manuscript, bound, 1).Count > 0, "Another configured subject was silently rebound.");

        bool missingReview = false;
        try { ManuscriptReader.VerifyEditorialApproval(manuscript, config with { RequireEditorialApproval = true }); }
        catch (InvalidDataException) { missingReview = true; }
        Check(missingReview, "Unreviewed manuscript passed the editorial hand-off.");
        var statusRoot = Path.Combine(Path.GetDirectoryName(manuscriptRoot)!, "chapters");
        Directory.CreateDirectory(statusRoot);
        var statusFile = Path.Combine(statusRoot, "01-temple-alpha.status.json");
        File.WriteAllText(statusFile, Data.Write(new ChapterResult(manuscript.Subject, "AI_APPROVED_PENDING_HUMAN", root,
            Data.Hash(File.ReadAllText(markdown)), "offline fixture")));
        ManuscriptReader.VerifyEditorialApproval(manuscript, config with { RequireEditorialApproval = true });
        File.WriteAllText(statusFile, Data.Write(new ChapterResult(manuscript.Subject, "CHAPTER_READY_NEEDS_REVIEW", root,
            Data.Hash(File.ReadAllText(markdown)), "unresolved")));
        bool unresolvedRejected = false;
        try { ManuscriptReader.VerifyEditorialApproval(manuscript, config with { RequireEditorialApproval = true }); }
        catch (InvalidDataException) { unresolvedRejected = true; }
        Check(unresolvedRejected, "Unresolved editorial findings passed.");

        Check(CommonsImageSource.ReusableLicense("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"), "CC BY rejected.");
        Check(CommonsImageSource.ReusableLicense("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"), "CC BY-SA rejected.");
        Check(!CommonsImageSource.ReusableLicense("CC BY-NC", "https://creativecommons.org/licenses/by-nc/4.0/"), "Noncommercial license accepted.");
        Check(!CommonsImageSource.ReusableLicense("Fair use", "https://creativecommons.org/licenses/by/4.0/"), "Conflicting license accepted.");
        Check(!CommonsImageSource.AllowedUri("http://upload.wikimedia.org/a.jpg")
            && !CommonsImageSource.AllowedUri("https://127.0.0.1/a.jpg")
            && !CommonsImageSource.AllowedUri("https://upload.wikimedia.org.attacker.test/a.jpg"), "Unsafe download URL accepted.");
        using (var invalidMetadata = JsonDocument.Parse(Metadata("CC BY-ND 4.0", "https://creativecommons.org/licenses/by-nd/4.0/")))
            Check(CommonsImageSource.Parse(invalidMetadata.RootElement).Count == 0, "Restricted candidate passed filtering.");
        Console.WriteLine("PASS four shared books, arbitrary subject counts, stable IDs, profiles, editorial hand-off and source/license filtering");

        var webHandler = new WebHandler();
        using var webHttp = new HttpClient(webHandler);
        using var web = new CommonsImageSource(webHttp);
        var modelHandler = new ModelHandler(manuscript);
        using var modelHttp = new HttpClient(modelHandler);
        using var api = new ProductionApi(config, "OFFLINE", NullLogger.Instance, modelHttp);
        var pipeline = new IllustratedPipeline(config, "OFFLINE FIXTURE", api, NullLogger.Instance, web);
        var final = await pipeline.RunAsync(manuscript, Path.Combine(root, "web-success"), CancellationToken.None);
        Check(File.Exists(final) && modelHandler.ImageCalls == 0, "webOnly bought generated art or failed to deliver.");
        Check(modelHandler.SawPhotoInventory, "Planner did not receive available photographs before describing scenes.");
        Check(modelHandler.PhotoReviewHadNoArtBrief, "Photograph review received speculative generated character/scene instructions.");
        Check(modelHandler.PhotoPagesHadNoArtBrief && modelHandler.PhotoPageContexts > 0, "Final page reviewer inherited a generated illustration brief for a photograph.");
        var run = Path.GetDirectoryName(final)!;
        var layout = Data.Read<LayoutManifest>(File.ReadAllText(Path.Combine(run, "layout-1.json")));
        Check(layout.Text.Any(t => t.Kind == "image-credit" && t.Text.Contains("Fixture photographer")), "Photographer credit missing from PDF.");
        Check(layout.Text.Any(t => t.Kind == "image-credit" && t.Text.Contains("creativecommons.org")), "License missing from PDF.");
        string joinedCredits = System.Text.RegularExpressions.Regex.Replace(string.Concat(layout.Text.Where(t => t.Kind == "image-credit").Select(t => t.Text)), @"\s", "");
        Check(joinedCredits.Contains(LongCreditUrl), "Long archive URL was truncated, hyphenated or changed while wrapping credits.");
        Check(ChapterPdfLayout.Verify(final, manuscript, layout, config).Passed, "Credit pages broke exact source comparison.");
        int storyEnd = layout.Text.Where(t => t.Kind == "paragraph").Max(t => t.Page);
        var sparseBeforeCredits = layout with
        {
            Text = layout.Text.Where(t => t.Page != storyEnd || t.Kind != "paragraph")
                .Concat(layout.Text.Where(t => t.Page == storyEnd && t.Kind == "paragraph").Take(2)).ToList(),
            Images = layout.Images.Where(i => i.Page != storyEnd).ToList()
        };
        Check(ChapterPdfLayout.Verify(final, manuscript, sparseBeforeCredits, config).Issues.Any(i => i.Contains("Nearly empty")),
            "Credits concealed a sparse final narrative page.");
        using (var archive = ZipFile.OpenRead(Directory.GetFiles(run, "*.epub").Single()))
        using (var stream = archive.GetEntry("OEBPS/chapter.xhtml")!.Open())
        {
            var text = XDocument.Load(stream).ToString();
            Check(text.Contains("Fixture photographer") && text.Contains("creativecommons.org"), "EPUB credits missing.");
        }
        int modelCalls = modelHandler.Calls, networkCalls = webHandler.Calls;
        await pipeline.RunAsync(manuscript, Path.Combine(root, "web-success"), CancellationToken.None);
        Check(modelHandler.Calls == modelCalls && webHandler.Calls == networkCalls, "Identical web/image/page work was not cached.");
        ChapterPdfLayout.RenderPages(final, Path.Combine(run, "offline-verified-pages"));
        Console.WriteLine("PASS web-only full pipeline: photo instead of generated image; PDF/EPUB credits; exact story; cache-only rerun");

        modelHandler.RejectPageSemantics = true;
        int priorPageCalls = modelHandler.PageReviewCalls;
        bool semanticStopped = false;
        string semanticRoot = Path.Combine(root, "semantic-page-failure");
        try { await pipeline.RunAsync(manuscript, semanticRoot, CancellationToken.None); }
        catch (ProductionReviewException) { semanticStopped = true; }
        Check(semanticStopped && modelHandler.PageReviewCalls == priorPageCalls + 1
            && Directory.GetFiles(semanticRoot, "*_print.pdf", SearchOption.AllDirectories).Length == 0,
            "Semantic rejection purchased more page reviews/layout retries or promoted a final PDF.");
        modelHandler.RejectPageSemantics = false;

        using var noWebHttp = new HttpClient(new WebHandler { Empty = true });
        using var noWeb = new CommonsImageSource(noWebHttp);
        bool stopped = false;
        try
        {
            await new IllustratedPipeline(config, "OFFLINE FIXTURE", api, NullLogger.Instance, noWeb)
                .RunAsync(manuscript, Path.Combine(root, "web-missing"), CancellationToken.None);
        }
        catch (ProductionReviewException) { stopped = true; }
        Check(stopped && modelHandler.ImageCalls == 0, "webOnly silently generated an image without a suitable source.");
        var fallback = config with { ImageMode = "preferWeb" };
        using var fallbackApi = new ProductionApi(fallback, "OFFLINE", NullLogger.Instance, modelHttp);
        await new IllustratedPipeline(fallback, "OFFLINE FIXTURE", fallbackApi, NullLogger.Instance, noWeb)
            .RunAsync(manuscript, Path.Combine(root, "web-fallback"), CancellationToken.None);
        Check(modelHandler.ImageCalls == 1, "preferWeb failed to generate exactly one fallback scene.");
        modelHandler.RejectWebPhoto = true;
        bool nonPhotoRejected = false;
        try
        {
            await new IllustratedPipeline(config, "OFFLINE FIXTURE", api, NullLogger.Instance, web)
                .RunAsync(manuscript, Path.Combine(root, "web-not-photo"), CancellationToken.None);
        }
        catch (ProductionReviewException) { nonPhotoRejected = true; }
        Check(nonPhotoRejected && modelHandler.ImageCalls == 1, "A high-scoring non-photograph bypassed the real-photo gate.");
        Console.WriteLine("PASS missing sources: webOnly stops; preferWeb uses bounded generated fallback. No real network/model calls.");
    }

    private static IllustrationPlan Plan(Manuscript manuscript) => new(
        new CharacterReference(manuscript.Subject, "documented period", "region", "temple", "not applicable", "not applicable",
            "distinctive facade", "site setting", ["structure"], ["invented features"]),
        [new IllustrationScene("I01", manuscript.Subject, ["P001"], "P001", "Establishing view", "3:2",
            "Match exact site", ["watermarks"], "Offline photograph fixture")], []);

    private static ImageReview Review() => new(true, true, true, true, true, true, true, true, true, true, [])
    {
        StyleScore = 75, CharacterScore = 75, QualityScore = 75,
        StyleComparison = "Offline fixture photographic presentation", CharacterComparison = "Offline fixture subject identity"
    };

    private static string Metadata(string license = "CC BY 4.0", string url = "https://creativecommons.org/licenses/by/4.0/")
        => JsonSerializer.Serialize(new { query = new { pages = new[] { new
        {
            pageid = 42, title = "File:Temple Alpha.jpg", imageinfo = new[] { new
            {
                url = "https://upload.wikimedia.org/fixture.jpg", width = 1800, height = 1200, mime = "image/jpeg",
                extmetadata = new { Artist = new { value = "Fixture photographer" }, Credit = new { value = LongCreditUrl },
                    LicenseShortName = new { value = license }, LicenseUrl = new { value = url } }
            } }
        } } } });

    private static byte[] ImageBytes()
    {
        using var bitmap = new SKBitmap(1800, 1200);
        using var canvas = new SKCanvas(bitmap);
        canvas.Clear(new SKColor(40, 185, 194));
        using var data = bitmap.Encode(SKEncodedImageFormat.Png, 100);
        return data.ToArray();
    }

    private sealed class WebHandler : HttpMessageHandler
    {
        public int Calls;
        public bool Empty;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Calls++;
            HttpContent body = request.RequestUri!.Host == "en.wikipedia.org"
                ? new StringContent("{}", Encoding.UTF8, "application/json")
                : request.RequestUri.Host == "commons.wikimedia.org"
                ? new StringContent(Empty ? "{}" : Metadata(), Encoding.UTF8, "application/json")
                : new ByteArrayContent(ImageBytes());
            if (body is ByteArrayContent) body.Headers.ContentType = new("image/png");
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = body });
        }
    }

    private sealed class ModelHandler(Manuscript manuscript) : HttpMessageHandler
    {
        public int Calls, ImageCalls;
        public bool RejectWebPhoto;
        public bool SawPhotoInventory;
        public bool PhotoReviewHadNoArtBrief;
        public bool PhotoPagesHadNoArtBrief = true, RejectPageSemantics;
        public int PhotoPageContexts, PageReviewCalls;
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Calls++;
            using var json = JsonDocument.Parse(await request.Content!.ReadAsStringAsync(ct));
            object response;
            if (request.RequestUri!.AbsolutePath.EndsWith("/images"))
            {
                ImageCalls++;
                response = new { data = new[] { new { b64_json = Convert.ToBase64String(ImageBytes()) } } };
            }
            else
            {
                string? name = json.RootElement.GetProperty("response_format").GetProperty("json_schema").GetProperty("name").GetString();
                if (name == "IllustrationPlan")
                    SawPhotoInventory = json.RootElement.GetProperty("messages")[1].GetProperty("content")[0].GetProperty("text")
                        .GetString()!.Contains("availableWebImages", StringComparison.Ordinal);
                if (name == "WebImageReview")
                {
                    using var photoInput = JsonDocument.Parse(json.RootElement.GetProperty("messages")[1].GetProperty("content")[0].GetProperty("text").GetString()!);
                    PhotoReviewHadNoArtBrief = !photoInput.RootElement.TryGetProperty("character", out _)
                        && !photoInput.RootElement.TryGetProperty("scene", out _);
                }
                if (name == "PageReview")
                {
                    PageReviewCalls++;
                    using var pageInput = JsonDocument.Parse(json.RootElement.GetProperty("messages")[1].GetProperty("content")[0].GetProperty("text").GetString()!);
                    foreach (var image in pageInput.RootElement.GetProperty("illustrations").EnumerateArray())
                        if (image.TryGetProperty("sourceKind", out var kind) && kind.GetString() == "wikimedia-photograph")
                        { PhotoPageContexts++; PhotoPagesHadNoArtBrief &= !image.TryGetProperty("Scene", out _); }
                }
                object answer = name switch
                {
                    "IllustrationPlan" => Plan(manuscript),
                    "ImageReview" => Review(),
                    "WebImageReview" => new WebImageReview(!RejectWebPhoto, !RejectWebPhoto, Review()),
                    "PageReview" => RejectPageSemantics
                        ? new PageReview(false, true, true, true, true, true, true, false, true, ["Offline semantic rejection"], [])
                        : new PageReview(true, true, true, true, true, true, true, true, true, [], []),
                    _ => throw new InvalidOperationException("Unexpected schema " + name)
                };
                response = new { choices = new[] { new { finish_reason = "stop", message = new { content = JsonSerializer.Serialize(answer) } } } };
            }
            return new HttpResponseMessage(HttpStatusCode.OK)
            { Content = new StringContent(JsonSerializer.Serialize(response), Encoding.UTF8, "application/json") };
        }
    }

    private static void Check(bool condition, string reason)
    { if (!condition) throw new InvalidOperationException(reason); }
}
