using GreatIndians.Factory;
using GreatIndians.Factory.Production;

internal static class ImageReviewSettingsTests
{
    private static void Check(bool valid, string message)
    {
        if (!valid) throw new Exception("Image review settings: " + message);
    }
    public static void Run()
    {
        var config = Data.Read<ProductionConfig>("""
            {"imageMode":"webOnly","profile":"scientific-biography","imageReview":{
            "photographStyle":"archival","photographInstructions":"Prefer authentic research photographs.",
            "generatedArtworkInstructions":"Retain the existing colourful painted art direction.",
            "allowBlackAndWhite":true,"allowArchivalWear":true,"requireOpeningPortrait":true}}
            """);
        config.Validate();
        string photo = ProfilePrompts.Review(config, true);
        string generated = ProfilePrompts.Review(config, false);
        Check(photo.StartsWith("You independently review real photographs") && !photo.Contains(ProductionPrompts.ReviewImage),
            "Photograph reviewer inherited generated-art review instructions.");
        Check(photo.Contains("Prefer authentic research photographs.") && !photo.Contains(config.ImageReview.GeneratedArtworkInstructions),
            "Photograph instructions were missing or contaminated by artwork guidance.");
        Check(generated.Contains(config.ImageReview.GeneratedArtworkInstructions) && !generated.Contains("Prefer authentic research photographs."),
            "Generated and photographic guidance were mixed.");
        Check(photo.Contains("Black-and-white and sepia archival photographs are acceptable") && photo.Contains("Allow minor grain"), "Archival preferences missing.");
        Check(photo.Contains("An adult portrait introduces the biography") && photo.Contains("70/100"), "Portrait/context rule or threshold missing.");
        var strict = config with { ImageReview = config.ImageReview with { AllowBlackAndWhite = false, AllowArchivalWear = false, RequireOpeningPortrait = false } };
        string strictPrompt = ProfilePrompts.Review(strict, true);
        Check(strictPrompt.Contains("requires colour photographs") && strictPrompt.Contains("without material visible archival damage")
            && strictPrompt.Contains("a relevant site or object may establish"), "Configured switches ignored.");
        Check(ProfilePrompts.Review(config with { ImageReview = config.ImageReview with { PhotographStyle = "editorial" } }, true)
            .Contains("clear factual visual communication"), "Editorial preset ignored.");
        bool invalid = false;
        try { (config with { ImageReview = config.ImageReview with { PhotographStyle = "unknown" } }).Validate(); }
        catch (InvalidDataException) { invalid = true; }
        Check(invalid, "Unknown review style was silently accepted.");
        Check(Data.Read<ProductionConfig>("{}").ImageReview.AllowBlackAndWhite, "Legacy config compatibility lost.");
        Console.WriteLine("PASS configurable image review: photo/art prompt isolation, documentary/archival/editorial styles, portrait and archival switches, required checks and legacy defaults");
    }
}
