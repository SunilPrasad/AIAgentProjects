using PdfSharp.Drawing;

namespace GreatIndians.Factory.Production;

/// <summary>Author's master design tokens; shared by layout, EPUB and review prompts.</summary>
public static class ProductionDesign
{
    public const string Version = "liberation-master-v3";
    public const string FontFamily = "Liberation Serif";
    public const string FontPrefix = "LiberationSerif-";
    public const double BodySize = 12.1;
    public const double DefaultLeading = 17;
    public const double TitleSize = 22;
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
        figure{margin:1em 0;break-inside:avoid;}
        img{max-width:100%;height:auto;display:block;margin:auto;}
        """;

    public static XColor Colour(string hex)
        => XColor.FromArgb(Convert.ToInt32(hex[1..], 16) | unchecked((int)0xff000000));

    public static string Description(ProductionConfig config)
        => $"Ages 8–12. 432 × 648pt full-colour pages; warm ivory {Paper}. " +
            $"Body: {FontFamily} Regular {BodySize}pt, ink {Body}, leading {BodySize * config.LineSpacing:F2}pt. " +
            $"One centred original chapter title: {FontFamily} Bold {TitleSize}pt {Title}. " +
            $"Chapter number: Bold {ChapterSize}pt {Gold}. Page numbers: Regular {PageNumberSize}pt {PageNumber}. " +
            "Embedded fonts, selectable unchanged paragraphs, mirrored margins and a safe gutter. " +
            "Vibrant cinematic Indian historical children's storybook art with rich watercolour-and-gouache textures, " +
            "expressive characters, warm golden sunlight, luminous skies, lush foliage and atmospheric depth. " +
            $"Art palette: sky {Sky}, turquoise {Turquoise}, emerald {Emerald}, sunshine {Sunshine}, coral {Coral}. " +
            "Complete heads/headwear/hands/important objects; 10–15% headroom; no artwork text or destructive cropping.";
}
