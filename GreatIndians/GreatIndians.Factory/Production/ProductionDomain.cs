using System.Text.Json.Serialization;

namespace GreatIndians.Factory.Production;

public sealed record ProductionConfig
{
    public string BookTitle { get; init; } = "Legends of Ancient India";
    public string Subtitle { get; init; } = "10 Inspiring True Stories of Great Kings, Brilliant Minds and Visionaries for Kids Ages 8–12";
    public string ManuscriptsDirectory { get; init; } = "../output/final-chapters";
    public string OutputDirectory { get; init; } = "../output/illustrated";
    public string IllustrationStyle { get; init; } = "illustration-style.md";
    public string StyleReferenceImage { get; init; } = "assets/reference/art-style-reference.png";
    public string PlannerModel { get; init; } = "openai/gpt-4.1";
    public string ImageModel { get; init; } = "google/gemini-3-pro-image";
    public string VisionModel { get; init; } = "anthropic/claude-sonnet-4.5";
    public string ImageResolution { get; init; } = "2K";
    public int IllustrationCount { get; init; } = 4;
    public int MaxImageAttempts { get; init; } = 3;
    public int MinimumImageScore { get; init; } = 70;
    public int MaxLayoutAttempts { get; init; } = 2;
    public int MaxApiAttempts { get; init; } = 3;
    public int MinimumImageDpi { get; init; } = 300;
    public double FontSize { get; init; } = ProductionDesign.BodySize;
    public double LineSpacing { get; init; } = ProductionDesign.DefaultLeading / ProductionDesign.BodySize;
    public int BookPageCountForGutter { get; init; }
    public bool CreateEpub { get; init; } = true;
    public string[] Subjects { get; init; } =
    [
        "Baudhayana", "Chanakya", "Chandragupta Maurya", "Ashoka the Great", "Samudragupta",
        "Aryabhata", "Brahmagupta", "Rajaraja Chola I", "Bhaskaracharya", "Chhatrapati Shivaji Maharaj"
    ];

    public void Validate()
    {
        if (IllustrationCount is < 4 or > 7 || MaxImageAttempts is < 1 or > 5
            || MinimumImageScore is < 70 or > 95
            || MaxLayoutAttempts is < 1 or > 3 || MaxApiAttempts is < 1 or > 5
            || MinimumImageDpi < 300 || Math.Abs(FontSize - ProductionDesign.BodySize) > 0.000001
            || FontSize * LineSpacing < 16.5 || FontSize * LineSpacing > 17.5
            || BookPageCountForGutter is < 0 or > 828 || Subjects is not { Length: 10 }
            || Subjects.Any(string.IsNullOrWhiteSpace) || Subjects.Distinct().Count() != Subjects.Length
            || new[] { PlannerModel, ImageModel, VisionModel }.Any(model => string.IsNullOrWhiteSpace(model) || !model.Contains('/')))
        {
            throw new InvalidDataException("Invalid production configuration. Use a minimum image score of 70–95. The master design requires 12.1pt body text and 16.5–17.5pt leading; use 4–7 illustrations, 300+ PPI and the ten supplied subjects.");
        }
    }
}

public sealed record TextRun(string Text, bool Italic = false, bool Bold = false);
public sealed record ManuscriptParagraph(string Id, string OriginalMarkdown, string Text, List<TextRun> Runs);
public sealed record Manuscript(
    string SourcePath, string SourceSha256, string Title, string Subject, int ChapterNumber,
    List<ManuscriptParagraph> Paragraphs, List<string> SuppressedHeadings);

public sealed record CharacterReference(
    [property: JsonRequired] string Name,
    [property: JsonRequired] string Period,
    [property: JsonRequired] string Region,
    [property: JsonRequired] string Role,
    [property: JsonRequired] string Clothing,
    [property: JsonRequired] string HairAndHeadwear,
    [property: JsonRequired] string Appearance,
    [property: JsonRequired] string Environment,
    [property: JsonRequired] List<string> Objects,
    [property: JsonRequired] List<string> Avoid);
public sealed record IllustrationScene(
    [property: JsonRequired] string Id,
    [property: JsonRequired] string Subject,
    [property: JsonRequired] List<string> ParagraphIds,
    [property: JsonRequired] string InsertBeforeParagraphId,
    [property: JsonRequired] string Description,
    [property: JsonRequired] string AspectRatio,
    [property: JsonRequired] string AccuracyRequirements,
    [property: JsonRequired] List<string> NegativeConstraints,
    [property: JsonRequired] string AltText);
public sealed record IllustrationPlan(
    [property: JsonRequired] CharacterReference Character,
    [property: JsonRequired] List<IllustrationScene> Scenes,
    [property: JsonRequired] List<string> EditorialNotes);
public sealed record ImageReview(
    [property: JsonRequired] bool Approved,
    [property: JsonRequired] bool CorrectSubject,
    [property: JsonRequired] bool FullHeadVisible,
    [property: JsonRequired] bool ImportantFeaturesVisible,
    [property: JsonRequired] bool NoGeneratedText,
    [property: JsonRequired] bool AnatomySound,
    [property: JsonRequired] bool HistoricallyPlausible,
    [property: JsonRequired] bool MatchesPassage,
    [property: JsonRequired] bool ConsistentCharacter,
    [property: JsonRequired] bool SharpEnough,
    [property: JsonRequired] List<string> Issues)
{
    [JsonRequired]
    public bool MatchesVisualStyle { get; init; } = true;

    [JsonRequired]
    public bool ReferenceColourAndLightMatch { get; init; }
    [JsonRequired]
    public bool PainterlyDetailMatches { get; init; }
    [JsonRequired]
    public bool CharacterFeaturesMatch { get; init; }
    [JsonRequired]
    public string StyleComparison { get; init; } = "";
    [JsonRequired]
    public string CharacterComparison { get; init; } = "";

    [JsonRequired]
    public int StyleScore { get; init; }
    [JsonRequired]
    public int CharacterScore { get; init; }
    [JsonRequired]
    public int QualityScore { get; init; }
    [JsonRequired]
    public List<string> Suggestions { get; init; } = [];

    [JsonIgnore]
    public double OverallScore => Math.Round(StyleScore * 0.4 + CharacterScore * 0.3 + QualityScore * 0.3, 1);

    public bool Accepts(int minimumScore) => Passes && OverallScore >= minimumScore;

    [JsonIgnore]
    public bool Passes => CorrectSubject && FullHeadVisible && ImportantFeaturesVisible
        && NoGeneratedText && AnatomySound && HistoricallyPlausible && MatchesPassage
        && ConsistentCharacter && SharpEnough
        && StyleScore is >= 50 and <= 100 && CharacterScore is >= 50 and <= 100 && QualityScore is >= 50 and <= 100
        && OverallScore >= 70 && Suggestions is not null
        && !string.IsNullOrWhiteSpace(StyleComparison) && !string.IsNullOrWhiteSpace(CharacterComparison)
        && Issues is { Count: 0 };
}
public sealed record PageReview(
    [property: JsonRequired] bool Approved,
    [property: JsonRequired] bool TextReadable,
    [property: JsonRequired] bool NoClipping,
    [property: JsonRequired] bool NoOverlap,
    [property: JsonRequired] bool OneHeadlineOnly,
    [property: JsonRequired] bool CorrectSubject,
    [property: JsonRequired] bool IllustrationsUncropped,
    [property: JsonRequired] bool ImagesMatchPassages,
    [property: JsonRequired] bool PageNumberCorrect,
    [property: JsonRequired] List<string> Issues,
    [property: JsonRequired] List<string> EditorialNotes)
{
    [JsonIgnore]
    public bool Passes => Approved && TextReadable && NoClipping && NoOverlap && OneHeadlineOnly
        && CorrectSubject && IllustrationsUncropped && ImagesMatchPassages && PageNumberCorrect
        && Issues is { Count: 0 } && EditorialNotes is not null;
}
public sealed record AcceptedArtwork(
    IllustrationScene Scene, string Path, string Sha256, int PixelWidth, int PixelHeight, ImageReview Review);
public sealed record ImagePlacement(string SceneId, int Page, double X, double Y, double Width, double Height, double EffectiveDpi);
public sealed record TextPlacement(string Kind, string? ParagraphId, int Page, double X, double Y, string Text);
public sealed record LayoutManifest(
    double WidthPoints, double HeightPoints, double InsideMarginPoints, int PageCount,
    List<ImagePlacement> Images, List<TextPlacement> Text, string PdfSha256);
public sealed record LayoutChecks(bool Passed, List<string> Issues, string ExpectedTextHash, string ExtractedTextHash);
public sealed class ProductionReviewException(string message) : Exception(message);
