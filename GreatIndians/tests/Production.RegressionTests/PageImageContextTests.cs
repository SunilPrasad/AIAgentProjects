using GreatIndians.Factory;
using GreatIndians.Factory.Production;

internal static class PageImageContextTests
{
    public static void Run()
    {
        var manuscript = new Manuscript("source.md", "hash", "Scientist", "Scientist", 1,
            [new("P001", "Born in India.", "Born in India.", [new("Born in India.")])], []);
        var scene = new IllustrationScene("I01", "Scientist", ["P001"], "P001", "A Bengali-style royal blue robe in a staged laboratory",
            "3:2", "Invented costume brief for generated artwork", [], "Art direction");
        var review = new ImageReview(true, true, true, true, true, true, true, true, true, true, [])
        { VisibleIdentity = "Adult scientist in a dark Western suit", StyleScore = 80, CharacterScore = 90, QualityScore = 80 };
        var artwork = new AcceptedArtwork(scene, "photo.png", "hash", 1200, 1800, review);
        var photo = artwork with { Credit = new WebImageCredit("Archival portrait", "Photographer", "CC BY 4.0",
            "https://creativecommons.org/licenses/by/4.0/", "https://commons.wikimedia.org/?curid=1", "https://upload.wikimedia.org/photo.jpg", "Archive", "original") };
        string photoInput = Data.Write(PageImageContext.For(manuscript, photo));
        string generatedInput = Data.Write(PageImageContext.For(manuscript, artwork));
        if (!photoInput.Contains("wikimedia-photograph") || !photoInput.Contains("dark Western suit")
            || photoInput.Contains("royal blue robe") || photoInput.Contains("Invented costume")
            || !generatedInput.Contains("royal blue robe"))
            throw new Exception("Page photo context inherited the generated illustration brief or lost source identity.");
        var passed = new PageReview(true, true, true, true, true, true, true, true, true, [], []);
        if (PageImageContext.CanFixByRelayout(passed with { ImagesMatchPassages = false })
            || PageImageContext.CanFixByRelayout(passed with { CorrectSubject = false })
            || !PageImageContext.CanFixByRelayout(passed with { NoClipping = false }))
            throw new Exception("Semantic page failures were treated as repairable by resizing.");
        string prompt = ProfilePrompts.PageReview(new ProductionConfig { ImageMode = "webOnly" });
        var optional = new ProductionConfig { ImageMode = "webOnly", MissingWebImagePolicy = "skip" };
        var wrongPhoto = passed with { Approved = false, CorrectSubject = false, NoOverlap = false };
        if (PageImageContext.PhotoToOmit(optional, wrongPhoto, [photo]) != photo
            || PageImageContext.PhotoToOmit(optional, wrongPhoto, [photo, photo]) is not null
            || PageImageContext.PhotoToOmit(optional, wrongPhoto, [artwork]) is not null
            || PageImageContext.PhotoToOmit(optional with { MissingWebImagePolicy = "stop" }, wrongPhoto, [photo]) is not null
            || PageImageContext.PhotoToOmit(optional, passed with { Approved = false, NoClipping = false }, [photo]) is not null)
            throw new Exception("Photo omission recovery bypassed policy, ambiguously identified an image, or ignored a layout-only failure.");
        if (!prompt.Contains("An adult portrait correctly introduces") || !prompt.Contains("Still reject actual wrong identities"))
            throw new Exception("Page photograph rules weaken checks or lack the documentary introduction policy.");
        Console.WriteLine("PASS page review: documentary context excludes invented costumes/scenes, generated context retained, valid portrait introductions and bounded semantic failures");
    }
}
