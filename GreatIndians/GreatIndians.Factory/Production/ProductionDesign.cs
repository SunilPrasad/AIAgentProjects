using PdfSharp.Drawing;

namespace GreatIndians.Factory.Production;

/// <summary>Author's master design tokens; shared by layout, EPUB and review prompts.</summary>
public static class ProductionDesign
{
    public const string Version = "retained-section-headings-v6";
    public const string FontFamily = "Liberation Serif";
    public const string FontPrefix = "LiberationSerif-";
    public const double BodySize = 12.1;
    public const double DefaultLeading = 17;
    public const double TitleSize = 22;
    public const double HeadingSize = 14;
    public const double HeadingLeading = 18;
    public const double ChapterSize = 10;
    public const double PageNumberSize = 9;
    public const string Paper = "#FFFDF6";
    public const string Title = "#0C348B";
    public const string Body = "#1D2636";
    public const string Gold = "#B16A14";
    public const string PageNumber = "#213A73";
    public const string Sky = "#4DAAF2";
    public const string Turquoise = "#28B9C2";
    public const string Emerald = "#48A65A";
    public const string Sunshine = "#F8C94D";
    public const string Coral = "#EF7950";

    public static string EpubCss => $$"""
        @font-face{font-family:'Liberation Serif';src:url('fonts/{{FontPrefix}}Regular.ttf');}
        @font-face{font-family:'Liberation Serif';src:url('fonts/{{FontPrefix}}Bold.ttf');font-weight:bold;}
        @font-face{font-family:'Liberation Serif';src:url('fonts/{{FontPrefix}}Italic.ttf');font-style:italic;}
        @font-face{font-family:'Liberation Serif';src:url('fonts/{{FontPrefix}}BoldItalic.ttf');font-style:italic;font-weight:bold;}
        body{font-family:'Liberation Serif',serif;font-size:1em;line-height:1.405;margin:5%;background:{{Paper}};color:{{Body}};}
        p{margin:0 0 1em;}
        h1{font-size:1.82em;text-align:center;color:{{Title}};border-top:1px solid {{Gold}};padding-top:1em;}
        h2,h3,h4,h5,h6{font-size:1.157em;font-weight:bold;color:{{Body}};line-height:1.286;margin:1em 0 .4em;break-after:avoid;page-break-after:avoid;}
        figure{margin:1em 0;break-inside:avoid;}
        img{max-width:100%;height:auto;display:block;margin:auto;}
        """;

    public static XColor Colour(string hex)
        => XColor.FromArgb(Convert.ToInt32(hex[1..], 16) | unchecked((int)0xff000000));

    public static string Description(ProductionConfig config)
        => $"Ages {config.AudienceMinAge}–{config.AudienceMaxAge}. 432 × 648pt full-colour pages; warm ivory {Paper}. " +
            $"Body: {FontFamily} Regular {BodySize}pt, ink {Body}, leading {BodySize * config.LineSpacing:F2}pt. " +
            $"One centred original chapter title: {FontFamily} Bold {TitleSize}pt {Title}. " +
            $"Retained section headings: left-aligned {FontFamily} Bold {HeadingSize}pt {Body}, {HeadingLeading}pt leading, kept with their following paragraph. " +
            $"Chapter number: Bold {ChapterSize}pt {Gold}. Page numbers: Regular {PageNumberSize}pt {PageNumber}. " +
            "Embedded fonts, selectable unchanged paragraphs, mirrored margins and a safe gutter. " +
            (config.ImageMode == "webOnly"
                ? "Reviewed Wikimedia photographs only; AI image generation disabled. Preserve photographic appearance and authentic incidental inscriptions; " +
                    "do not recolour, repaint, stretch or destructively crop. Complete important features and print-safe placement are required."
                : "Generated illustrations: vibrant cinematic nonfiction children's storybook art with rich watercolour-and-gouache textures, " +
            "expressive characters, warm golden sunlight, luminous skies, lush foliage and atmospheric depth. " +
            $"Art palette: sky {Sky}, turquoise {Turquoise}, emerald {Emerald}, sunshine {Sunshine}, coral {Coral}. " +
            (ContentProfiles.IsPerson(config.Profile)
                ? "Complete heads/headwear/hands/important objects; 10–15% headroom; "
                : "Complete important structures/objects; consistent architecture and safe surrounding space; ") +
            "no generated artwork text or destructive cropping. " +
            (config.ImageMode == "generated" ? "" : "Real photographs keep their photographic appearance and authentic incidental inscriptions; do not recolour/repaint them to match the generated palette."));
}
