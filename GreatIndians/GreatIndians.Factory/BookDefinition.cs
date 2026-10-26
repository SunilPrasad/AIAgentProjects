using System.Text.RegularExpressions;
using GreatIndians.Factory.Production;

namespace GreatIndians.Factory;

public sealed record SubjectDefinition
{
    public string Id { get; init; } = "";
    public string Name { get; init; } = "";
    public string[] Aliases { get; init; } = [];
    public string ImageQuery { get; init; } = "";
    public string[] CommonsFiles { get; init; } = [];
}

/// <summary>One definition is shared by writing and illustrated production.</summary>
public sealed record BookDefinition
{
    public int SchemaVersion { get; init; } = 1;
    public string Id { get; init; } = "";
    public string Title { get; init; } = "";
    public string Subtitle { get; init; } = "";
    public string Author { get; init; } = "";
    public string Profile { get; init; } = "nonfiction";
    public int AudienceMinAge { get; init; } = 8;
    public int AudienceMaxAge { get; init; } = 12;
    public string Language { get; init; } = "British English";
    public bool RequireEditorialApproval { get; init; } = true;
    public string OutputRoot { get; init; } = "../output/books";
    public SubjectDefinition[] Subjects { get; init; } = [];
    public BookConfig Writing { get; init; } = new();
    public ProductionConfig Production { get; init; } = new();

    public static BookDefinition Load(string path)
    {
        var book = Data.Read<BookDefinition>(File.ReadAllText(path));
        book.Validate();
        return book;
    }

    public void Validate()
    {
        if (SchemaVersion != 1 || !ValidId(Id) || string.IsNullOrWhiteSpace(Title)
            || !ContentProfiles.All.Contains(Profile) || AudienceMinAge < 1 || AudienceMaxAge < AudienceMinAge
            || string.IsNullOrWhiteSpace(OutputRoot) || string.IsNullOrWhiteSpace(Language)
            || Writing is null || Production is null || Subjects is not { Length: > 0 }
            || Subjects.Any(s => s is null || !ValidId(s.Id) || string.IsNullOrWhiteSpace(s.Name)
                || s.Aliases is null || s.CommonsFiles is null || s.Aliases.Any(string.IsNullOrWhiteSpace)
                || s.CommonsFiles.Any(f => !f.StartsWith("File:", StringComparison.Ordinal)))
            || Subjects.Select(s => s.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() != Subjects.Length
            || Subjects.Select(s => s.Name).Distinct(StringComparer.OrdinalIgnoreCase).Count() != Subjects.Length)
            throw new InvalidDataException("Invalid book definition: require a unique safe book/subject ID, title, subjects and supported content profile.");
        var identifiers = Subjects.SelectMany(s => new[] { s.Name }.Concat(s.Aliases)).ToArray();
        if (identifiers.Distinct(StringComparer.OrdinalIgnoreCase).Count() != identifiers.Length)
            throw new InvalidDataException("Subject names and aliases must identify one subject unambiguously.");
    }

    private static bool ValidId(string id) => Regex.IsMatch(id ?? "", "^[a-z0-9]+(?:-[a-z0-9]+)*$");
    private string Root(string definitionPath) => Path.Combine(
        Path.GetFullPath(OutputRoot, Path.GetDirectoryName(Path.GetFullPath(definitionPath))!), Id);

    private static string Asset(string path, string candidate, string defaultName, string bundled)
    {
        var local = Path.GetFullPath(candidate, Path.GetDirectoryName(Path.GetFullPath(path))!);
        return !File.Exists(local) && candidate == defaultName ? Path.Combine(AppContext.BaseDirectory, bundled) : local;
    }

    public BookConfig ForWriting(string path) => Writing with
    {
        BookTitle = Title, BookId = Id, Profile = Profile, SubjectDefinitions = Subjects,
        Personalities = Subjects.Select(s => s.Name).ToList(), AudienceMinAge = AudienceMinAge,
        AudienceMaxAge = AudienceMaxAge, Language = Language, OutputDirectory = Root(path),
        StyleBible = Asset(path, Writing.StyleBible, "style-bible.md", "profiles/common-style.md")
    };

    public ProductionConfig ForProduction(string path) => Production with
    {
        BookTitle = Title, BookId = Id, Subtitle = Subtitle, Author = Author, Profile = Profile,
        RequireEditorialApproval = RequireEditorialApproval,
        AudienceMinAge = AudienceMinAge, AudienceMaxAge = AudienceMaxAge,
        SubjectDefinitions = Subjects, Subjects = Subjects.Select(s => s.Name).ToArray(),
        ManuscriptsDirectory = Path.Combine(Root(path), "final-chapters"),
        OutputDirectory = Path.Combine(Root(path), "illustrated"),
        IllustrationStyle = Asset(path, Production.IllustrationStyle, "illustration-style.md", "profiles/storybook-art.md"),
        StyleReferenceImage = string.IsNullOrWhiteSpace(Production.StyleReferenceImage) ? "" :
            Asset(path, Production.StyleReferenceImage, "assets/reference/art-style-reference.png", "assets/reference/art-style-reference.png")
    };
}

public static class ContentProfiles
{
    public static readonly string[] All = ["biography", "scientific-biography", "temple", "place", "event", "nonfiction"];
    public static bool IsPerson(string profile) => profile is "biography" or "scientific-biography";
    public static string Guidance(string profile) => profile switch
    {
        "biography" => "Follow the documented life, work, achievements and legacy. Never invent childhood, motives, dialogue or personal scenes.",
        "scientific-biography" => "Follow the scientist's documented life, work and legacy. Explain discoveries simply without distorting their meaning. Check discovery attribution, collaborators, dates and limitations. Avoid unsupported sole-inventor or first-ever claims and invented experiments.",
        "temple" => "Write about the actual temple: location, documented history, builders, rebuilding, architecture, worship and cultural significance. Distinguish religious belief and traditional stories from documented events with brief respectful attribution. Never present a miracle or legend as established history. Do not apply one religious tradition to every site or invent construction dates, rituals or architectural features.",
        "place" => "Explain the actual place, its location, documented development, distinctive features, people and significance. Distinguish present-day views from historical reconstructions. Do not invent architecture or events.",
        "event" => "Explain the documented setting, sequence, participants, causes and consequences. Separate evidence from interpretation. Do not invent dialogue or simplify contested responsibility into unsupported certainty.",
        _ => "Write clear evidence-based nonfiction about the supplied subject. Introduce it directly, build a coherent sequence of supported ideas and explain its significance. Do not force the topic into a person's life story, invent scenes or offer unsupported factual or practical instructions."
    };
}
