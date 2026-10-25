namespace GreatIndians.Factory.Production;

public static class ProductionPrompts
{
    public const string Version = "reference-character-v4";
    public const string NoText = "NO TEXT, NO LETTERS, NO WORDS, NO CAPTIONS, NO TITLES, NO LABELS, NO WATERMARKS, NO TYPOGRAPHY, NO WRITING, NO NUMBERS, NO LOGOS.";

    public static string Plan(string style, int sceneCount) =>
        "You are a historical children's-book art director, not a manuscript writer. Read the complete supplied manuscript. " +
        "The exact subject supplied is mandatory: do not substitute another person. Never rewrite or return a replacement manuscript. " +
        "Create a structured character reference with name, period, region, role, clothing, hairAndHeadwear, appearance, environment, objects and avoid. " +
        "Lock one adult visual identity throughout: specify apparent age range, face shape, skin tone, exact beard/moustache or clean-shaven state, " +
        "hairline, hairstyle/headwear and a distinctive period-appropriate clothing colour. Repeat these identifying traits in every scene with the subject. " +
        "Do not introduce ageing or facial-hair changes between scenes. Supporting people must look visibly different from the subject. " +
        "Use respectful historically plausible interpretation where appearance is undocumented, not a claimed authentic portrait. " +
        $"Plan exactly {sceneCount} distinct illustrations. Scene IDs are I01, I02, etc. Each scene has subject, paragraphIds, insertBeforeParagraphId, " +
        "description, aspectRatio, accuracyRequirements, negativeConstraints and altText. Use only supplied paragraph IDs. " +
        "Place scenes in manuscript order at distinct paragraph positions. I01 must precede P001 and use 3:2 landscape. " +
        "Distribute the remaining scenes across the story's beginning, middle and later passages according to their narrative relevance; " +
        "avoid clustering illustrations at adjacent opening paragraphs when equally suitable later passages exist. " +
        "I01 doubles as the character reference: show the exact subject as the single prominent main person with a clear face, " +
        "complete head/headwear, recognisable clothing and important hands. Do not use an object-only or distant crowd opening. " +
        "Later scenes use 16:9, 3:2, 4:3 or 1:1 and vary composition. Each scene must depict an activity or context supported by its passage. " +
        "Do not invent childhood events, conversations, royal status or relationships. Do not ask AI to draw formulas, labelled diagrams or an entire page. " +
        "Plan safe margins around complete heads, hair, headwear, hands and objects. Editorial concerns go in editorialNotes, never a rewrite. " +
        "Return only the required JSON object.\nVISUAL STYLE:\n" + style;

    public static string Image(Manuscript manuscript, CharacterReference character, IllustrationScene scene, string style, string? correction)
        => $"Create artwork only for '{manuscript.Subject}' in '{manuscript.Title}', part of Legends of Ancient India for ages 8–12. " +
            "Do not generate a book page, headings or manuscript text. Follow the supplied character reference consistently.\n" +
            "IMAGE REFERENCE ROLES are listed at the end of this request. Match the ART STYLE reference closely in colour saturation, " +
            "luminous golden directional light, rich blue/green backgrounds, dimensional painted faces and fabrics, fine detail and atmospheric depth. " +
            "Use rich watercolour-and-gouache texture without washing out the colours. Avoid muted tan washes, heavy comic outlines, flat cel shading " +
            "and simplified cartoon faces. The written master controls safety and typography; the image controls the intended painted finish. " +
            "Do NOT copy the example person's identity, " +
            "scene, clothing, buildings, cropping, lettering or historical errors. A reference labelled CHARACTER is for THIS " +
            "chapter; preserve exactly that person's face shape, age, skin tone, facial hair, hairline, hairstyle/headwear and clothing colours. " +
            "Do not replace a clean-shaven subject with a bearded teacher, or give a supporting character the subject's identity. " +
            "When no character image is supplied, use the written character sheet for identity.\n" +
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
        "referenceRoles identifies the purpose and order of all additional images. An art style reference is the visual target for finish, colour and lighting, " +
        "never the authoritative person or scene. The exact supplied historical subject and passage are authoritative. " +
        "For scene I01, reject unless the subject is the clearly visible, single prominent main person with enough face and clothing " +
        "detail to serve as a character reference for the rest of the chapter. Later scenes may legitimately show passage-supported objects or context. " +
        "Check subject/role, whole head and headwear, important hands/tools, unwanted letters/numbers/logos/watermarks, anatomy, period plausibility, " +
        "passage alignment, consistency with the reference, and sharpness. Do not claim unknown facial features are verified historical likeness. " +
        "Cropping, wrong subject, readable image text, anachronisms, distorted anatomy or inaccurate scientific concepts require rejection. " +
        "Write styleComparison describing the actual candidate versus the art-style reference: saturation, golden directional lighting, " +
        "painted dimensional faces/fabrics, texture, environment detail and atmospheric depth. A generic 'storybook' resemblance is insufficient. " +
        "Set referenceColourAndLightMatch=false for noticeably muted/pastel/tan colours or weak flat lighting compared with the reference. " +
        "Set painterlyDetailMatches=false for heavy outlines, cel shading, simplified cartoon faces or flat backgrounds instead of rich painted detail. " +
        "If no style image is supplied, compare these features with the written style. " +
        "Write characterComparison with observable face shape, age, skin tone, beard/moustache state, hair/headwear and clothing colour comparisons " +
        "against the accepted CHARACTER image, or against the written character sheet for I01. Set characterFeaturesMatch=false and consistentCharacter=false " +
        "if the main subject changes these features, or a different-looking supporting person takes the main role. " +
        "If the subject is absent in an allowed object-only scene, explicitly state that and check that no substitute person appears. " +
        "Do not infer a match merely from the shared historical role. Set matchesVisualStyle honestly against the supplied master style and image: " +
        "vibrant cinematic Indian historical children's storybook art, rich watercolour-and-gouache textures, expressive characters, " +
        "warm golden sunlight, luminous blue skies, lush green foliage, colourful fabrics and beautiful atmospheric depth. " +
        "Respect the supplied sky blue, turquoise, emerald, sunshine yellow and coral palette. Reject photorealistic, dull sepia, " +
        "monochrome, muddy shadows, overly busy compositions or flat vector/cartoon results. " +
        "Set every boolean honestly and list concrete issues. Approve only when every check passes; return only the required JSON.";

    public const string ReviewPage =
        "Review the actual rendered PDF page image as a children's-book production proof. The supplied page text is the authoritative " +
        "manuscript content for this page. Do not rewrite it or ask for historical prose changes. Record any factual/editorial concern " +
        "in editorialNotes separately. Check legibility, complete lines, no overflow/clipping, no image/text overlap, only one chapter headline " +
        "on the opening page and no secondary/running headlines elsewhere, correct historical subject, no cropped heads or key objects, " +
        "no unwanted text inside art, scene alignment, and the correct page number. Manuscript formulas are typeset text, not image lettering. " +
        "The deterministic PDF text comparison handles exact spelling and paragraph order; inspect visible presentation as well. " +
        "Also check the supplied visualStyle: warm ivory paper, centred royal-blue chapter title, warm-gold chapter number, " +
        "Liberation Serif typography and dark-blue page numbers; " +
        "Reject avoidable large empty areas or a nearly empty continuation page; allow normal end-of-chapter whitespace and print-safe margins. " +
        "reject a visibly different design. Approve only when all mandatory visual/text layout checks pass. Return only the required JSON.";
}
