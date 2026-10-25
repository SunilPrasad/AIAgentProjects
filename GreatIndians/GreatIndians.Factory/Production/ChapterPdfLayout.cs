using System.Text;
using System.Text.RegularExpressions;
using PdfSharp.Drawing;
using PdfSharp.Fonts;
using PdfSharp.Pdf;
using PdfSharp.Pdf.IO;
using SkiaSharp;
using UglyToad.PdfPig.DocumentLayoutAnalysis.TextExtractor;

namespace GreatIndians.Factory.Production;

public static class ChapterPdfLayout
{
    public const double Width = 432;
    public const double Height = 648;
    private const double Outer = 50.4;
    private const double Top = 65.04;
    private const double Bottom = 48;
    private static readonly object FontLock = new();

    private sealed class EmbeddedSerifResolver : IFontResolver
    {
        public byte[] GetFont(string faceName)
            => File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory, "assets", "fonts", faceName + ".ttf"));

        public FontResolverInfo ResolveTypeface(string familyName, bool isBold, bool isItalic)
            => new(ProductionDesign.FontPrefix + (isBold && isItalic ? "BoldItalic" : isBold ? "Bold" : isItalic ? "Italic" : "Regular"));
    }

    public static LayoutManifest Create(
        Manuscript manuscript, IReadOnlyList<AcceptedArtwork> artwork, ProductionConfig config,
        string path, double imageScale = 1)
    {
        config.Validate();
        lock (FontLock)
        {
            GlobalFontSettings.FontResolver ??= new EmbeddedSerifResolver();
        }
        using var pdf = new PdfDocument();
        pdf.Info.Title = manuscript.Title;
        pdf.Info.Subject = "Illustrated researched chapter proof — human publication approval pending";
        pdf.Info.Author = config.BookTitle;
        pdf.Info.CreationDate = DateTime.UnixEpoch;
        pdf.Info.ModificationDate = DateTime.UnixEpoch;
        var fonts = new Dictionary<(bool, bool, double), XFont>();
        XFont Font(bool italic, bool bold, double size)
        {
            var key = (italic, bold, size);
            if (!fonts.TryGetValue(key, out var font))
            {
                var style = (italic ? XFontStyleEx.Italic : XFontStyleEx.Regular)
                    | (bold ? XFontStyleEx.Bold : XFontStyleEx.Regular);
                fonts[key] = font = new XFont(ProductionDesign.FontFamily, size, style);
            }
            return font;
        }

        double inside = Math.Max(54.96, GutterPoints(config.BookPageCountForGutter));
        var images = new List<ImagePlacement>();
        var text = new List<TextPlacement>();
        var graphics = new List<XGraphics>();
        XGraphics canvas = null!;
        int pageNumber = 0;
        double left = 0;
        double right = 0;
        double y = 0;
        var blue = new XSolidBrush(ProductionDesign.Colour(ProductionDesign.Title));
        var ink = new XSolidBrush(ProductionDesign.Colour(ProductionDesign.Body));
        var chapterInk = new XSolidBrush(ProductionDesign.Colour(ProductionDesign.Gold));
        var pageNumberInk = new XSolidBrush(ProductionDesign.Colour(ProductionDesign.PageNumber));
        double lineHeight = config.FontSize * config.LineSpacing;

        void NewPage()
        {
            var page = pdf.AddPage();
            page.Width = XUnit.FromPoint(Width);
            page.Height = XUnit.FromPoint(Height);
            canvas = XGraphics.FromPdfPage(page);
            graphics.Add(canvas);
            pageNumber++;
            left = pageNumber % 2 == 1 ? inside : Outer;
            right = pageNumber % 2 == 1 ? Width - Outer : Width - inside;
            y = Top;
            canvas.DrawRectangle(new XSolidBrush(ProductionDesign.Colour(ProductionDesign.Paper)), 0, 0, Width, Height);
            canvas.DrawLine(new XPen(ProductionDesign.Colour(ProductionDesign.Gold), 0.75), left, 39.6, right, 39.6);
        }

        List<List<TextRun>> Wrap(IEnumerable<TextRun> runs, double size, double available)
        {
            var words = new List<List<TextRun>>();
            var current = new List<TextRun>();
            foreach (var run in runs)
            {
                foreach (Match match in Regex.Matches(run.Text, @"\S+|\s+"))
                {
                    if (char.IsWhiteSpace(match.Value[0]))
                    {
                        if (current.Count > 0)
                        {
                            words.Add(current);
                            current = [];
                        }
                    }
                    else
                    {
                        current.Add(run with { Text = match.Value });
                    }
                }
            }
            if (current.Count > 0)
            {
                words.Add(current);
            }
            var lines = new List<List<TextRun>>();
            var line = new List<TextRun>();
            double used = 0;
            double space = canvas.MeasureString(" ", Font(false, false, size)).Width;
            foreach (var word in words)
            {
                double width = word.Sum(run => canvas.MeasureString(run.Text, Font(run.Italic, run.Bold, size)).Width);
                if (width > available)
                {
                    throw new InvalidDataException("A manuscript token is wider than the reading column; no text was cropped or rewritten.");
                }
                if (line.Count > 0 && used + space + width > available)
                {
                    lines.Add(line);
                    line = [];
                    used = 0;
                }
                if (line.Count > 0)
                {
                    line.Add(new TextRun(" "));
                    used += space;
                }
                line.AddRange(word);
                used += width;
            }
            if (line.Count > 0)
            {
                lines.Add(line);
            }
            return lines;
        }

        void DrawLine(List<TextRun> runs, string kind, string? paragraphId, double size, double height, XBrush brush, bool centred = false)
        {
            double x = left;
            if (centred)
                x += (right - left - runs.Sum(run => canvas.MeasureString(run.Text, Font(run.Italic, run.Bold, size)).Width)) / 2;
            double startX = x;
            foreach (var run in runs)
            {
                var font = Font(run.Italic, run.Bold, size);
                canvas.DrawString(run.Text, font, brush, new XRect(x, y, right - x + 1, height), XStringFormats.TopLeft);
                x += canvas.MeasureString(run.Text, font).Width;
            }
            text.Add(new TextPlacement(kind, paragraphId, pageNumber, startX, y, string.Concat(runs.Select(run => run.Text))));
            y += height;
        }

        void DrawArtwork(AcceptedArtwork art)
        {
            if (ManuscriptReader.HashFile(art.Path) != art.Sha256 || !art.Review.Passes)
            {
                throw new InvalidDataException($"Artwork {art.Scene.Id} changed or has no passing review.");
            }
            double maximumHeight = 226.8 * imageScale;
            double scale = Math.Min(Math.Min(320.4, right - left) / art.PixelWidth, maximumHeight / art.PixelHeight);
            scale = Math.Min(scale, 72.0 / config.MinimumImageDpi);
            double width = art.PixelWidth * scale;
            double height = art.PixelHeight * scale;
            if (width < 100 || height < 90)
            {
                throw new InvalidDataException($"Artwork {art.Scene.Id} cannot be printed at a useful size at 300 PPI.");
            }
            if (y + height + 14 + lineHeight * 2 > Height - Bottom)
            {
                NewPage();
            }
            using var image = XImage.FromFile(art.Path);
            double x = left + (right - left - width) / 2;
            canvas.DrawImage(image, x, y, width, height); // Contain: no clipping rectangle, crop or stretch.
            double dpi = Math.Min(art.PixelWidth / (width / 72), art.PixelHeight / (height / 72));
            images.Add(new ImagePlacement(art.Scene.Id, pageNumber, x, y, width, height, dpi));
            y += height + 14;
        }

        NewPage();
        y = 70;
        DrawLine([new TextRun($"CHAPTER {manuscript.ChapterNumber}", Bold: true)], "chapter-number", null, ProductionDesign.ChapterSize, 19, chapterInk, centred: true);
        y += 11;
        foreach (var line in Wrap([new TextRun(manuscript.Title, Bold: true)], ProductionDesign.TitleSize, right - left))
        {
            DrawLine(line, "title", null, ProductionDesign.TitleSize, 28, blue, centred: true);
        }
        y += 14;

        foreach (var paragraph in manuscript.Paragraphs)
        {
            foreach (var art in artwork.Where(art => art.Scene.InsertBeforeParagraphId == paragraph.Id))
            {
                DrawArtwork(art);
            }
            var lines = Wrap(paragraph.Runs, config.FontSize, right - left);
            int next = 0;
            while (next < lines.Count)
            {
                int fit = (int)Math.Floor((Height - Bottom - y) / lineHeight);
                if (fit < Math.Min(2, lines.Count - next))
                {
                    NewPage();
                    continue;
                }
                int take = Math.Min(fit, lines.Count - next);
                if (lines.Count - next - take == 1 && take > 1)
                {
                    take--;
                }
                for (int index = 0; index < take; index++)
                {
                    DrawLine(lines[next++], "paragraph", paragraph.Id, config.FontSize, lineHeight, ink);
                }
                if (next < lines.Count)
                {
                    NewPage();
                }
            }
            y += 12;
        }

        // Footer numbers are drawn last and tracked independently from manuscript content.
        for (int index = 0; index < graphics.Count; index++)
        {
            var footer = (index + 1).ToString(System.Globalization.CultureInfo.InvariantCulture);
            graphics[index].DrawString(footer, Font(false, false, ProductionDesign.PageNumberSize), pageNumberInk,
                new XRect(0, Height - 33, Width, 13), XStringFormats.TopCenter);
            text.Add(new TextPlacement("footer", null, index + 1, Width / 2, Height - 33, footer));
            graphics[index].Dispose();
        }
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        pdf.Save(path);
        return new LayoutManifest(Width, Height, inside, pageNumber, images, text, ManuscriptReader.HashFile(path));
    }

    public static double GutterPoints(int pages) => pages switch
    {
        <= 150 => 27,
        <= 300 => 36,
        <= 500 => 45,
        <= 700 => 54,
        _ => 63
    };

    public static LayoutChecks Verify(string pdfPath, Manuscript manuscript, LayoutManifest manifest, ProductionConfig config)
    {
        var issues = new List<string>();
        ManuscriptReader.VerifySourceUnchanged(manuscript);
        if (ManuscriptReader.HashFile(pdfPath) != manifest.PdfSha256)
        {
            issues.Add("PDF bytes changed after layout.");
        }
        var expected = Data.Normalize(string.Join(" ", manifest.Text
            .Where(item => item.Kind is "title" or "paragraph").Select(item => item.Text)));
        var source = Data.Normalize(manuscript.Title + " " + string.Join(" ", manuscript.Paragraphs.Select(p => p.Text)));
        if (expected != source)
        {
            issues.Add("Layout text differs from the original manuscript or paragraph order.");
        }
        foreach (var paragraph in manuscript.Paragraphs)
        {
            var rendered = Data.Normalize(string.Join(" ", manifest.Text.Where(item => item.ParagraphId == paragraph.Id).Select(item => item.Text)));
            if (rendered != Data.Normalize(paragraph.Text))
            {
                issues.Add($"Paragraph {paragraph.Id} changed or is missing.");
            }
        }

        var actualNarrative = new List<string>();
        using (var pdf = UglyToad.PdfPig.PdfDocument.Open(pdfPath))
        {
            if (pdf.NumberOfPages != manifest.PageCount)
            {
                issues.Add("PDF page count differs from layout manifest.");
            }
            foreach (var page in pdf.GetPages())
            {
                if (page.Letters.Where(letter => !string.IsNullOrWhiteSpace(letter.Value)).Any(letter =>
                {
                    var family = (letter.FontName ?? "").Replace(" ", "", StringComparison.Ordinal);
                    if (!family.Contains("LiberationSerif", StringComparison.OrdinalIgnoreCase)) return true;
                    var size = letter.PointSize;
                    string expectedColour;
                    bool bold = false;
                    if (Math.Abs(size - ProductionDesign.BodySize) < 0.01) expectedColour = ProductionDesign.Body;
                    else if (Math.Abs(size - ProductionDesign.TitleSize) < 0.01) { expectedColour = ProductionDesign.Title; bold = true; }
                    else if (Math.Abs(size - ProductionDesign.ChapterSize) < 0.01) { expectedColour = ProductionDesign.Gold; bold = true; }
                    else if (Math.Abs(size - ProductionDesign.PageNumberSize) < 0.01) expectedColour = ProductionDesign.PageNumber;
                    else return true;
                    if (bold && !family.Contains("Bold", StringComparison.OrdinalIgnoreCase)) return true;
                    if (letter.Color is null) return true;
                    var colour = letter.Color.ToRGBValues();
                    int expectedRgb = Convert.ToInt32(expectedColour[1..], 16);
                    return Math.Abs(colour.Item1 - ((expectedRgb >> 16) & 255) / 255d) > 0.002
                        || Math.Abs(colour.Item2 - ((expectedRgb >> 8) & 255) / 255d) > 0.002
                        || Math.Abs(colour.Item3 - (expectedRgb & 255) / 255d) > 0.002;
                }))
                    issues.Add($"Page {page.Number} violates the master font, point-size, weight or text-colour specification.");
                if (Math.Abs(page.Width - Width) > 0.1 || Math.Abs(page.Height - Height) > 0.1)
                {
                    issues.Add($"Page {page.Number} is not 6 × 9 inches.");
                }
                var actual = Data.Normalize(ContentOrderTextExtractor.GetText(page));
                var pageExpected = Data.Normalize(string.Join(" ", manifest.Text.Where(item => item.Page == page.Number).Select(item => item.Text)));
                if (actual != pageExpected)
                {
                    issues.Add($"Extracted selectable text differs on page {page.Number}.");
                }
                // Remove only explicitly recorded layout labels, after comparing the complete page.
                var narrative = actual;
                var label = manifest.Text.FirstOrDefault(t => t.Page == page.Number && t.Kind == "chapter-number")?.Text;
                if (label is not null && narrative.StartsWith(label + " ", StringComparison.Ordinal))
                    narrative = narrative[(label.Length + 1)..];
                var footer = manifest.Text.Single(t => t.Page == page.Number && t.Kind == "footer").Text;
                if (narrative.EndsWith(" " + footer, StringComparison.Ordinal))
                    narrative = narrative[..^(footer.Length + 1)];
                actualNarrative.Add(narrative);
                if (page.Letters.Any(letter => letter.BoundingBox.Left < 18 || letter.BoundingBox.Right > Width - 18
                    || letter.BoundingBox.Bottom < 18 || letter.BoundingBox.Top > Height - 18))
                {
                    issues.Add($"Text glyph outside safe trim area on page {page.Number}.");
                }
                foreach (var image in manifest.Images.Where(image => image.Page == page.Number))
                {
                    if (page.Letters.Where(letter => !string.IsNullOrWhiteSpace(letter.Value)).Any(letter =>
                        letter.BoundingBox.Right > image.X && letter.BoundingBox.Left < image.X + image.Width
                        && Height - letter.BoundingBox.Bottom > image.Y && Height - letter.BoundingBox.Top < image.Y + image.Height))
                        issues.Add($"Selectable text overlaps illustration {image.SceneId} on page {page.Number}.");
                }
            }
        }
        foreach (var image in manifest.Images)
        {
            if (image.EffectiveDpi + 0.01 < config.MinimumImageDpi || image.X < 18 || image.Y < 18
                || image.X + image.Width > Width - 18 || image.Y + image.Height > Height - 18)
            {
                issues.Add($"Illustration {image.SceneId} has insufficient resolution or unsafe placement.");
            }
        }
        if (manifest.InsideMarginPoints < GutterPoints(Math.Max(config.BookPageCountForGutter, manifest.PageCount)))
        {
            issues.Add("Inside margin is insufficient for the specified page count.");
        }
        using (var pdf = PdfReader.Open(pdfPath, PdfDocumentOpenMode.Import))
        {
            var descriptors = pdf.Internals.GetAllObjects().OfType<PdfDictionary>()
                .Where(dictionary => dictionary.Elements.GetName("/Type") == "/FontDescriptor").ToList();
            if (descriptors.Count == 0 || descriptors.Any(dictionary => !dictionary.Elements.ContainsKey("/FontFile2")
                && !dictionary.Elements.ContainsKey("/FontFile3") && !dictionary.Elements.ContainsKey("/FontFile")))
            {
                issues.Add("Not all PDF fonts could be verified as embedded.");
            }
        }
        var extractedNarrative = Data.Normalize(string.Join(" ", actualNarrative));
        if (extractedNarrative != source) issues.Add("Extracted chapter narrative differs after removing layout-only numbering.");
        return new LayoutChecks(issues.Count == 0, issues, Data.Hash(source), Data.Hash(extractedNarrative));
    }

    public static List<string> RenderPages(string pdfPath, string directory)
    {
        if (!(OperatingSystem.IsWindows() || OperatingSystem.IsLinux() || OperatingSystem.IsMacOS())) throw new PlatformNotSupportedException("PDF rendering requires Windows, Linux or macOS.");
        Directory.CreateDirectory(directory);
        var paths = new List<string>();
        var bytes = File.ReadAllBytes(pdfPath);
        int page = 0;
#pragma warning disable CA1416 // Desktop platforms checked above; PDFtoImage's combined platform annotations confuse the analyser.
        foreach (var bitmap in PDFtoImage.Conversion.ToImages(bytes, options: new PDFtoImage.RenderOptions(Dpi: 144)))
#pragma warning restore CA1416
        {
            using (bitmap)
            using (var data = bitmap.Encode(SKEncodedImageFormat.Png, 100))
            {
                var path = Path.Combine(directory, $"page-{++page:D3}.png");
                File.WriteAllBytes(path, data.ToArray());
                paths.Add(path);
            }
        }
        return paths;
    }
}
