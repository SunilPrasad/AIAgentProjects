using System.Security.Cryptography;
using System.Text;
using Markdig;
using Markdig.Syntax;
using Markdig.Syntax.Inlines;

namespace GreatIndians.Factory.Production;

public static class ManuscriptReader
{
    public static Manuscript Load(string path, ProductionConfig config)
    {
        path = Path.GetFullPath(path);
        var raw = File.ReadAllBytes(path);
        var markdown = File.ReadAllText(path);
        var document = Markdown.Parse(markdown);
        string? title = null;
        var paragraphs = new List<ManuscriptParagraph>();
        var omitted = new List<string>();
        var headings = new List<ManuscriptHeading>();
        var pendingHeadings = new List<(int Level, string Text)>();

        foreach (var block in document)
        {
            if (block is HeadingBlock heading)
            {
                var text = Plain(ExtractRuns(heading.Inline));
                if (heading.Level == 1)
                {
                    if (title is not null || paragraphs.Count != 0)
                    {
                        throw new InvalidDataException("The manuscript must start with exactly one main Markdown headline.");
                    }
                    title = text;
                }
                else
                {
                    if (title is null || string.IsNullOrWhiteSpace(text))
                        throw new InvalidDataException("Section headings must follow the main title and contain text.");
                    pendingHeadings.Add((heading.Level, text));
                }
            }
            else if (block is ParagraphBlock paragraph)
            {
                if (title is null)
                {
                    throw new InvalidDataException("A main chapter headline is required before the narrative.");
                }
                var runs = ExtractRuns(paragraph.Inline);
                foreach (var section in pendingHeadings)
                    headings.Add(new ManuscriptHeading($"H{headings.Count + 1:D3}", section.Level, section.Text, $"P{paragraphs.Count + 1:D3}"));
                pendingHeadings.Clear();
                paragraphs.Add(new ManuscriptParagraph(
                    $"P{paragraphs.Count + 1:D3}", markdown[paragraph.Span.Start..(paragraph.Span.End + 1)],
                    Plain(runs), runs));
            }
            else
            {
                throw new InvalidDataException($"Unsupported manuscript block: {block.GetType().Name}. Nothing was silently omitted.");
            }
        }

        if (pendingHeadings.Count > 0)
            throw new InvalidDataException("A section heading must have a following narrative paragraph.");
        if (string.IsNullOrWhiteSpace(title) || paragraphs.Count < config.IllustrationCount)
        {
            throw new InvalidDataException("A title and enough narrative paragraphs for the requested illustrations are required.");
        }

        var filename = Path.GetFileNameWithoutExtension(path);
        var bound = config.SubjectDefinitions.Select((s, index) => new { Subject = s, Index = index })
            .Where(s => filename.Equals($"{s.Index + 1:D2}-{s.Subject.Id}", StringComparison.OrdinalIgnoreCase)).ToList();
        var matches = bound.Count == 1 ? [bound[0].Subject.Name] : config.Subjects.Where(subject =>
            title.Contains(subject, StringComparison.OrdinalIgnoreCase) || config.SubjectDefinitions.Any(s => s.Name == subject
                && s.Aliases.Any(alias => title.Contains(alias, StringComparison.OrdinalIgnoreCase)))).ToList();
        if (matches.Count != 1)
        {
            throw new InvalidDataException("Use the configured stable chapter filename, or a title identifying exactly one configured subject/name/alias.");
        }
        var subjectName = matches[0];
        return new Manuscript(path, Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant(), title,
            subjectName, Array.IndexOf(config.Subjects, subjectName) + 1, paragraphs, omitted)
        {
            SubjectId = config.SubjectDefinitions.FirstOrDefault(s => s.Name == subjectName)?.Id ?? "",
            Headings = headings,
            Profile = config.Profile
        };
    }

    private static string Plain(IEnumerable<TextRun> runs) => string.Concat(runs.Select(run => run.Text));

    private static List<TextRun> ExtractRuns(ContainerInline? container, bool italic = false, bool bold = false)
    {
        var runs = new List<TextRun>();
        if (container is null)
        {
            return runs;
        }
        foreach (var inline in container)
        {
            switch (inline)
            {
                case LiteralInline literal:
                    runs.Add(new TextRun(literal.Content.ToString(), italic, bold));
                    break;
                case LineBreakInline:
                    runs.Add(new TextRun(" ", italic, bold));
                    break;
                case EmphasisInline emphasis:
                    runs.AddRange(ExtractRuns(emphasis, italic || emphasis.DelimiterCount is 1 or 3, bold || emphasis.DelimiterCount >= 2));
                    break;
                case LinkInline link when !link.IsImage:
                    runs.AddRange(ExtractRuns(link, italic, bold));
                    break;
                case CodeInline code:
                    runs.Add(new TextRun(code.Content, italic, bold));
                    break;
                case HtmlEntityInline entity:
                    runs.Add(new TextRun(entity.Transcoded.ToString(), italic, bold));
                    break;
                default:
                    throw new InvalidDataException($"Unsupported inline manuscript syntax: {inline.GetType().Name}.");
            }
        }
        return runs;
    }

    public static string HashFile(string path)
        => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();

    public static void VerifySourceUnchanged(Manuscript manuscript)
    {
        if (HashFile(manuscript.SourcePath) != manuscript.SourceSha256)
        {
            throw new InvalidDataException("The authoritative Markdown changed during production. Finalisation stopped; rerun against the new source.");
        }
    }

    public static void VerifyEditorialApproval(Manuscript manuscript, ProductionConfig config)
    {
        if (!config.RequireEditorialApproval) return;
        var bookRoot = Path.GetDirectoryName(Path.GetDirectoryName(manuscript.SourcePath))!;
        var statusPath = Path.Combine(bookRoot, "chapters", Path.GetFileNameWithoutExtension(manuscript.SourcePath) + ".status.json");
        if (!File.Exists(statusPath)) throw new InvalidDataException("Missing editorial status for this manuscript; complete writing review first, or explicitly use --allow-unreviewed for a proof.");
        var result = Data.Read<ChapterResult>(File.ReadAllText(statusPath));
        if (result.Subject != manuscript.Subject || result.ContentHash != Data.Hash(File.ReadAllText(manuscript.SourcePath))
            || result.Status != "AI_APPROVED_PENDING_HUMAN" && !result.PublicationApproved)
            throw new InvalidDataException("Manuscript does not have matching completed mandatory editorial checks. Resolve findings, or explicitly use --allow-unreviewed for a proof.");
    }
}
