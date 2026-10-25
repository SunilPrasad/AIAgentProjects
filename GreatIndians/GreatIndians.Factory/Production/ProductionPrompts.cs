namespace GreatIndians.Factory.Production;

public static class ProductionPrompts
{
    public const string Version = "illustrated-proof-v1";
    public const string NoText = "NO TEXT, NO LETTERS, NO WORDS, NO CAPTIONS, NO TITLES, NO LABELS, NO WATERMARKS, NO TYPOGRAPHY, NO WRITING, NO NUMBERS, NO LOGOS.";

    public static string Plan(string style, int sceneCount) =>
        "You are a historical children's-book art director, not a manuscript writer. Read the complete supplied manuscript. " +
        "The exact subject supplied is mandatory: do not substitute another person. Never rewrite or return a replacement manuscript. " +
        "Create a structured character reference with name, period, region, role, clothing, hairAndHeadwear, appearance, environment, objects and avoid. " +
        "Use respectful historically plausible interpretation where appearance is undocumented, not a claimed authentic portrait. " +
        $"Plan exactly {sceneCount} distinct illustrations. Scene IDs are I01, I02, etc. Each scene has subject, paragraphIds, insertBeforeParagraphId, " +
        "description, aspectRatio, accuracyRequirements, negativeConstraints and altText. Use only supplied paragraph IDs. " +
        "Place scenes in manuscript order at distinct paragraph positions. I01 must precede P001 and use 3:4 portrait. " +
        "Later scenes use 16:9, 3:2, 4:3 or 1:1 and vary composition. Each scene must depict an activity or context supported by its passage. " +
        "Do not invent childhood events, conversations, royal status or relationships. Do not ask AI to draw formulas, labelled diagrams or an entire page. " +
        "Plan safe margins around complete heads, hair, headwear, hands and objects. Editorial concerns go in editorialNotes, never a rewrite. " +
        "Return only the required JSON object.\nVISUAL STYLE:\n" + style;

    public static string Image(Manuscript manuscript, CharacterReference character, IllustrationScene scene, string style, string? correction)
        => $"Create artwork only for '{manuscript.Subject}' in '{manuscript.Title}', part of Legends of Ancient India for ages 8–12. " +
            "Do not generate a book page, headings or manuscript text. Follow the supplied character reference consistently.\n" +
            "CHARACTER REFERENCE:\n" + Data.Write(character) + "\nSCENE:\n" + scene.Description +
            "\nSUPPORTED PASSAGE:\n" + string.Join("\n", manuscript.Paragraphs.Where(p => scene.ParagraphIds.Contains(p.Id)).Select(p => p.Text)) +
            $"\nCOMPOSITION: {scene.AspectRatio}. Complete head, hair, turban/crown, chin, important hands and tools visible. " +
            "Reserve 10–15% breathing room. No edge-cut anatomy. No tight close-up. No modern instruments or fantasy armour. " +
            "Manuscripts may be blank or have indistinct non-readable marks. Do not draw scientific formulas or inaccurate diagrams.\n" +
            scene.AccuracyRequirements + "\nAVOID:\n" + string.Join("; ", scene.NegativeConstraints) + "\n" + NoText +
            "\nSTYLE:\n" + style + "\nCORRECTIONS FROM PRIOR REVIEW:\n" + (correction ?? "None.");

    public const string ReviewImage =
        "Independently inspect the actual supplied raster image, not merely its prompt. The first image is the candidate; " +
        "a second image, when present, is the accepted character reference. The exact supplied historical subject and passage are authoritative. " +
        "Check subject/role, whole head and headwear, important hands/tools, unwanted letters/numbers/logos/watermarks, anatomy, period plausibility, " +
        "passage alignment, consistency with the reference, and sharpness. Do not claim unknown facial features are verified historical likeness. " +
        "Cropping, wrong subject, readable image text, anachronisms, distorted anatomy or inaccurate scientific concepts require rejection. " +
        "Set every boolean honestly and list concrete issues. Approve only when every check passes; return only the required JSON.";

    public const string ReviewPage =
        "Review the actual rendered PDF page image as a children's-book production proof. The supplied page text is the authoritative " +
        "manuscript content for this page. Do not rewrite it or ask for historical prose changes. Record any factual/editorial concern " +
        "in editorialNotes separately. Check legibility, complete lines, no overflow/clipping, no image/text overlap, only one chapter headline " +
        "on the opening page and no secondary/running headlines elsewhere, correct historical subject, no cropped heads or key objects, " +
        "no unwanted text inside art, scene alignment, and the correct page number. Manuscript formulas are typeset text, not image lettering. " +
        "The deterministic PDF text comparison handles exact spelling and paragraph order; inspect visible presentation as well. " +
        "Approve only when all mandatory visual/text layout checks pass. Return only the required JSON.";
}
