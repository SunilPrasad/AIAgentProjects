using System.IO.Compression;
using System.Text;
using System.Xml.Linq;

namespace GreatIndians.Factory.Production;

public static class ChapterEpub
{
    public static void Create(Manuscript manuscript, List<AcceptedArtwork> artwork, ProductionConfig config, string path)
    {
        XNamespace html = "http://www.w3.org/1999/xhtml";
        var body = new XElement(html + "body", new XElement(html + "h1", manuscript.Title));
        foreach (var paragraph in manuscript.Paragraphs)
        {
            foreach (var image in artwork.Where(a => a.Scene.InsertBeforeParagraphId == paragraph.Id))
                body.Add(new XElement(html + "figure", new XElement(html + "img",
                    new XAttribute("src", "images/" + image.Scene.Id + ".png"), new XAttribute("alt", image.Scene.AltText))));
            var p = new XElement(html + "p", new XAttribute("id", paragraph.Id));
            foreach (var run in paragraph.Runs)
            {
                object node = new XText(run.Text);
                if (run.Italic) node = new XElement(html + "em", node);
                if (run.Bold) node = new XElement(html + "strong", node);
                p.Add(node);
            }
            body.Add(p);
        }
        var chapter = new XDocument(new XElement(html + "html", new XAttribute(XNamespace.Xml + "lang", "en"),
            new XElement(html + "head", new XElement(html + "title", manuscript.Title),
                new XElement(html + "link", new XAttribute("rel", "stylesheet"), new XAttribute("href", "style.css"))), body));
        XNamespace opf = "http://www.idpf.org/2007/opf";
        XNamespace dc = "http://purl.org/dc/elements/1.1/";
        var manifest = new XElement(opf + "manifest",
            new XElement(opf + "item", new XAttribute("id", "chapter"), new XAttribute("href", "chapter.xhtml"), new XAttribute("media-type", "application/xhtml+xml")),
            new XElement(opf + "item", new XAttribute("id", "nav"), new XAttribute("href", "nav.xhtml"), new XAttribute("media-type", "application/xhtml+xml"), new XAttribute("properties", "nav")),
            new XElement(opf + "item", new XAttribute("id", "css"), new XAttribute("href", "style.css"), new XAttribute("media-type", "text/css")));
        foreach (var a in artwork) manifest.Add(new XElement(opf + "item", new XAttribute("id", a.Scene.Id),
            new XAttribute("href", "images/" + a.Scene.Id + ".png"), new XAttribute("media-type", "image/png")));
        string[] fontFaces = ["Regular", "Bold", "Italic", "BoldItalic"];
        foreach (var face in fontFaces)
            manifest.Add(new XElement(opf + "item", new XAttribute("id", "font-" + face),
                new XAttribute("href", "fonts/LiberationSerif-" + face + ".ttf"), new XAttribute("media-type", "font/ttf")));
        manifest.Add(new XElement(opf + "item", new XAttribute("id", "font-license"),
            new XAttribute("href", "fonts/LICENSE.txt"), new XAttribute("media-type", "text/plain")));
        var package = new XDocument(new XElement(opf + "package", new XAttribute("version", "3.0"), new XAttribute("unique-identifier", "uid"),
            new XElement(opf + "metadata", new XElement(dc + "identifier", new XAttribute("id", "uid"), "urn:sha256:" + manuscript.SourceSha256),
                new XElement(dc + "title", manuscript.Title), new XElement(dc + "language", "en"),
                new XElement(opf + "meta", new XAttribute("property", "dcterms:modified"), "2026-01-01T00:00:00Z")),
            manifest, new XElement(opf + "spine", new XElement(opf + "itemref", new XAttribute("idref", "chapter")))));
        XNamespace epub = "http://www.idpf.org/2007/ops";
        var nav = new XDocument(new XElement(html + "html", new XAttribute(XNamespace.Xml + "lang", "en"),
            new XElement(html + "head", new XElement(html + "title", "Contents")),
            new XElement(html + "body", new XElement(html + "nav", new XAttribute(epub + "type", "toc"),
                new XElement(html + "ol", new XElement(html + "li", new XElement(html + "a", new XAttribute("href", "chapter.xhtml"), manuscript.Title)))))));
        var temporary = path + ".partial";
        using (var output = new FileStream(temporary, FileMode.Create, FileAccess.Write))
        using (var archive = new ZipArchive(output, ZipArchiveMode.Create))
        {
            void Write(string name, string text, CompressionLevel level = CompressionLevel.Optimal)
            { using var writer = new StreamWriter(archive.CreateEntry(name, level).Open(), new UTF8Encoding(false)); writer.Write(text); }
            Write("mimetype", "application/epub+zip", CompressionLevel.NoCompression);
            Write("META-INF/container.xml", "<?xml version=\"1.0\"?><container version=\"1.0\" xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\"><rootfiles><rootfile full-path=\"OEBPS/package.opf\" media-type=\"application/oebps-package+xml\"/></rootfiles></container>");
            Write("OEBPS/chapter.xhtml", chapter.ToString()); Write("OEBPS/nav.xhtml", nav.ToString()); Write("OEBPS/package.opf", package.ToString());
            Write("OEBPS/style.css", ProductionDesign.EpubCss);
            foreach (var a in artwork) archive.CreateEntryFromFile(a.Path, "OEBPS/images/" + a.Scene.Id + ".png");
            foreach (var face in fontFaces)
                archive.CreateEntryFromFile(Path.Combine(AppContext.BaseDirectory, "assets", "fonts", "LiberationSerif-" + face + ".ttf"),
                    "OEBPS/fonts/LiberationSerif-" + face + ".ttf");
            archive.CreateEntryFromFile(Path.Combine(AppContext.BaseDirectory, "assets", "fonts", "Liberation-LICENSE.txt"), "OEBPS/fonts/LICENSE.txt");
        }
        using (var archive = ZipFile.OpenRead(temporary))
        {
            if (archive.Entries[0].FullName != "mimetype")
                throw new ProductionReviewException("EPUB mimetype must be its first ZIP entry.");
            using (var reader = new StreamReader(archive.Entries[0].Open()))
                if (reader.ReadToEnd() != "application/epub+zip")
                    throw new ProductionReviewException("EPUB mimetype is invalid.");
            foreach (var entry in archive.Entries.Where(e => e.FullName.EndsWith(".xhtml") || e.FullName.EndsWith(".opf") || e.FullName.EndsWith(".xml")))
            {
                using var xml = entry.Open();
                _ = XDocument.Load(xml);
            }
            using (var packageStream = archive.GetEntry("OEBPS/package.opf")!.Open())
            {
                var reopened = XDocument.Load(packageStream);
                var items = reopened.Descendants(opf + "item").ToList();
                if (items.Any(item => archive.GetEntry("OEBPS/" + item.Attribute("href")!.Value) is null)
                    || reopened.Descendants(opf + "itemref").Any(reference => !items.Any(item => item.Attribute("id")?.Value == reference.Attribute("idref")?.Value)))
                    throw new ProductionReviewException("EPUB manifest or spine contains a broken reference.");
            }
            using var stream = archive.GetEntry("OEBPS/chapter.xhtml")!.Open();
            var document = XDocument.Load(stream);
            var paragraphs = document.Descendants(html + "p").ToList();
            if (paragraphs.Count != manuscript.Paragraphs.Count || paragraphs.Where((p, i) => p.Value != manuscript.Paragraphs[i].Text).Any()
                || document.Descendants(html + "h1").Single().Value != manuscript.Title)
                throw new ProductionReviewException("EPUB selectable text differs from the manuscript.");
            if (document.Descendants(html + "img").Any(image => string.IsNullOrWhiteSpace(image.Attribute("alt")?.Value)
                || archive.GetEntry("OEBPS/" + image.Attribute("src")!.Value) is null))
                throw new ProductionReviewException("EPUB image reference or alternative text is missing.");
        }
        ManuscriptReader.VerifySourceUnchanged(manuscript);
        File.Move(temporary, path, true);
    }
}
