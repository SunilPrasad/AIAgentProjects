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
                    omitted.Add(markdown[heading.Span.Start..(heading.Span.End + 1)]);
                }
            }
            else if (block is ParagraphBlock paragraph)
            {
                if (title is null)
                {
                    throw new InvalidDataException("A main chapter headline is required before the narrative.");
                }
                var runs = ExtractRuns(paragraph.Inline);
                paragraphs.Add(new ManuscriptParagraph(
                    $"P{paragraphs.Count + 1:D3}", markdown[paragraph.Span.Start..(paragraph.Span.End + 1)],
                    Plain(runs), runs));
            }
            else
            {
                throw new InvalidDataException($"Unsupported manuscript block: {block.GetType().Name}. Nothing was silently omitted.");
            }
        }

        if (string.IsNullOrWhiteSpace(title) || paragraphs.Count < config.IllustrationCount)
        {
            throw new InvalidDataException("A title and enough narrative paragraphs for the requested illustrations are required.");
        }

        var matches = config.Subjects.Where(subject => title.Contains(subject, StringComparison.OrdinalIgnoreCase)).ToList();
        if (matches.Count != 1)
        {
            throw new InvalidDataException("The chapter title must identify exactly one of the configured ten historical subjects.");
        }
        var subjectName = matches[0];
        return new Manuscript(path, Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant(), title,
            subjectName, Array.IndexOf(config.Subjects, subjectName) + 1, paragraphs, omitted);
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
}
