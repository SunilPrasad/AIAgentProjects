namespace GreatIndians.Factory.Production;

public static class ProductionPrompts
{
    public const string Version = "reference-style-v2";
    public const string NoText = "NO TEXT, NO LETTERS, NO WORDS, NO CAPTIONS, NO TITLES, NO LABELS, NO WATERMARKS, NO TYPOGRAPHY, NO WRITING, NO NUMBERS, NO LOGOS.";

    public static string Plan(string style, int sceneCount) =>
        "You are a historical children's-book art director, not a manuscript writer. Read the complete supplied manuscript. " +
        "The exact subject supplied is mandatory: do not substitute another person. Never rewrite or return a replacement manuscript. " +
        "Create a structured character reference with name, period, region, role, clothing, hairAndHeadwear, appearance, environment, objects and avoid. " +
        "Use respectful historically plausible interpretation where appearance is undocumented, not a claimed authentic portrait. " +
        $"Plan exactly {sceneCount} distinct illustrations. Scene IDs are I01, I02, etc. Each scene has subject, paragraphIds, insertBeforeParagraphId, " +
        "description, aspectRatio, accuracyRequirements, negativeConstraints and altText. Use only supplied paragraph IDs. " +
        "Place scenes in manuscript order at distinct paragraph positions. I01 must precede P001 and use 3:2 landscape. " +
        "I01 doubles as the character reference: show the exact subject as the single prominent main person with a clear face, " +
        "complete head/headwear, recognisable clothing and important hands. Do not use an object-only or distant crowd opening. " +
        "Later scenes use 16:9, 3:2, 4:3 or 1:1 and vary composition. Each scene must depict an activity or context supported by its passage. " +
        "Do not invent childhood events, conversations, royal status or relationships. Do not ask AI to draw formulas, labelled diagrams or an entire page. " +
        "Plan safe margins around complete heads, hair, headwear, hands and objects. Editorial concerns go in editorialNotes, never a rewrite. " +
        "Return only the required JSON object.\nVISUAL STYLE:\n" + style;

    public static string Image(Manuscript manuscript, CharacterReference character, IllustrationScene scene, string style, string? correction)
        => $"Create artwork only for '{manuscript.Subject}' in '{manuscript.Title}', part of Legends of Ancient India for ages 8–12. " +
            "Do not generate a book page, headings or manuscript text. Follow the supplied character reference consistently.\n" +
            "IMAGE REFERENCE ROLES are listed at the end of this request. An ART STYLE reference only guides rich warm colour, " +
            "painted brushwork, contrast, depth and children's storybook finish. Do NOT copy the example person's identity, " +
            "scene, clothing, buildings, cropping, lettering or historical errors. A reference labelled CHARACTER is for THIS " +
            "chapter; preserve that person's appearance. When no character image is supplied, use the written character sheet for identity.\n" +
            "CHARACTER REFERENCE:\n" + Data.Write(character) + "\nSCENE:\n" + scene.Description +
            "\nSUPPORTED PASSAGE:\n" + string.Join("\n", manuscript.Paragraphs.Where(p => scene.ParagraphIds.Contains(p.Id)).Select(p => p.Text)) +
            $"\nCOMPOSITION: {scene.AspectRatio}. Complete head, hair, turban/crown, chin, important hands and tools visible. " +
            "Reserve 10–15% breathing room. No edge-cut anatomy. No tight close-up. No modern instruments or fantasy armour. " +
            "Any visible manuscript surface must be completely blank; preferably show a closed scroll or its plain reverse. " +
            "No pseudo-script, decorative glyphs or marks resembling letters. Do not draw scientific formulas or inaccurate diagrams.\n" +
            scene.AccuracyRequirements + "\nAVOID:\n" + string.Join("; ", scene.NegativeConstraints) + "\n" + NoText +
            "\nSTYLE:\n" + style + "\nCORRECTIONS FROM PRIOR REVIEW:\n" + (correction ?? "None.");

    public const string ReviewImage =
        "Independently inspect the actual supplied raster image, not merely its prompt. The first image is the candidate; " +
        "referenceRoles identifies the purpose and order of all additional images. An art style reference is only a palette/brushwork example, " +
        "never the authoritative person or scene. The exact supplied historical subject and passage are authoritative. " +
        "For scene I01, reject unless the subject is the clearly visible, single prominent main person with enough face and clothing " +
        "detail to serve as a character reference for the rest of the chapter. Later scenes may legitimately show passage-supported objects or context. " +
        "Check subject/role, whole head and headwear, important hands/tools, unwanted letters/numbers/logos/watermarks, anatomy, period plausibility, " +
        "passage alignment, consistency with the reference, and sharpness. Do not claim unknown facial features are verified historical likeness. " +
        "Cropping, wrong subject, readable image text, anachronisms, distorted anatomy or inaccurate scientific concepts require rejection. " +
        "Set matchesVisualStyle honestly: compare bright saturated saffron/gold, turquoise/blue and green palette, hand-painted storybook " +
        "brushwork, clean contours and warm luminous light with the supplied style reference. Reject photorealistic, dull sepia or flat vector results. " +
        "Set every boolean honestly and list concrete issues. Approve only when every check passes; return only the required JSON.";

    public const string ReviewPage =
        "Review the actual rendered PDF page image as a children's-book production proof. The supplied page text is the authoritative " +
        "manuscript content for this page. Do not rewrite it or ask for historical prose changes. Record any factual/editorial concern " +
        "in editorialNotes separately. Check legibility, complete lines, no overflow/clipping, no image/text overlap, only one chapter headline " +
        "on the opening page and no secondary/running headlines elsewhere, correct historical subject, no cropped heads or key objects, " +
        "no unwanted text inside art, scene alignment, and the correct page number. Manuscript formulas are typeset text, not image lettering. " +
        "The deterministic PDF text comparison handles exact spelling and paragraph order; inspect visible presentation as well. " +
        "Also check the supplied visualStyle: cream paper, centred blue chapter/title, serif typography and gold top rule; " +
        "reject a visibly different design. Approve only when all mandatory visual/text layout checks pass. Return only the required JSON.";
}
