namespace GreatIndians.Factory.Production;

public static class ProductionPrompts
{
    public const string Version = "scored-review-v6";
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
        "Image models reliably add fake script to any writing surface that faces the viewer, so never make reading, writing, carving, " +
        "calculating or drawing in sand the visible focus. Show manuscripts closed, tied or edge-on, inscriptions from a distance or angle, " +
        "and calculations through gesture, instruments or the night sky rather than marks; add this to the scene's negativeConstraints. " +
        "In the character reference state hair length, parting and whether the subject is clean-shaven or bearded in plain words. " +
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
        "Review the actual candidate image for a children's biography, using the labelled references. " +
        "Use a practical scored acceptance policy, not exact imitation or perfection. " +
        "Return integer styleScore, characterScore and qualityScore from 0 to 100. " +
        "Scale: 90–100 excellent; 80–89 strong; 70–79 usable with minor compromises; 50–69 noticeable weaknesses; below 50 unsuitable. " +
        "Overall score is 40% style + 30% character + 30% quality. The supplied minimumImageScore is the acceptance threshold, " +
        "with a minimum of 50 in each category. Do not demand 90-level perfection for a 70-level acceptance threshold. " +
        "Style: assess appealing colour, lighting, readable composition, painted finish and resemblance to the art-style reference. " +
        "Visible contour lines, partly line-drawn fabric folds, less dimensional modelling or moderate differences in texture are " +
        "acceptable compromises when the illustration remains colourful, attractive and suitable for ages 8–12. " +
        "Character: I01 ESTABLISHES the visual identity. The written appearance is an art-direction suggestion, not historical evidence. " +
        "For I01, plausible adult-age differences, loose versus tied hair, missing decorative hair bands, clothing shades, borders and draping " +
        "are soft differences: do not mark correctSubject, historicallyPlausible or consistentCharacter false for them. " +
        "For later scenes, the accepted CHARACTER IMAGE takes precedence over conflicting written appearance details. " +
        "Match the recognisable person, especially face, skin tone and facial hair; allow small hairstyle, pose and garment variations. " +
        "A clearly different main person or major unexplained identity change fails consistentCharacter. " +
        "For an allowed object-only scene, state that no character is depicted and assess whether a substitute person was introduced. " +
        "Quality: assess readable action, attractive composition, usable detail and anatomical coherence. " +
        "Hard rejection flags are wrong subject/role, cropped head or important features, visible generated writing, significant distorted anatomy, " +
        "clear anachronisms, unsupported scene, clearly different character or unusable sharpness. " +
        "For I01 require one identifiable prominent subject suitable as the later character reference. " +
        "Do not claim undocumented faces or speculative clothing colours are verified historical facts. " +
        "Put ONLY hard rejection reasons in issues. Put minor art-direction differences and improvements in suggestions. " +
        "Write concrete styleComparison and characterComparison observations. " +
        "In visibleIdentity describe only what the main person in the CANDIDATE looks like, in one sentence: apparent age, face shape, " +
        "skin tone, clean-shaven or the exact facial hair, hair length/parting/tie, headwear and main clothing colours. " +
        "Write 'no main person' when none is depicted. The booleans matchesVisualStyle, " +
        "referenceColourAndLightMatch, painterlyDetailMatches and characterFeaturesMatch describe close matching, " +
        "but false values for these soft criteria alone do not veto an otherwise acceptable scored image. " +
        "Set approved according to the hard flags and supplied numerical threshold, not perfection. Return only the required JSON.";
    public const string ReviewPage =
        "Terminal image-credit pages are allowed. Credit text is not source narrative and does not need a chapter headline. " +
        "Real web photographs may have photographic style and authentic incidental inscriptions; do not require painterly " +
        "finish or removal of real inscriptions. Reject added watermarks, wrong subjects and important cropping. " +
        "Illustrations have already passed the configured scored image review. Do not reject a page for accepted soft compromises " +
        "in brushwork, contour lines, fabric shading, apparent adult age, hairstyle or clothing shades. " +
        "The opening image establishes identity; do not reimpose the speculative written appearance. " +
        "Review the actual rendered PDF page image as a children's-book production proof. The supplied page text is the authoritative " +
        "manuscript content for this page. Do not rewrite it or ask for historical prose changes. Record any factual/editorial concern " +
        "in editorialNotes separately. Check legibility, complete lines, no overflow/clipping, no image/text overlap, only one chapter headline " +
        "on the opening page and no secondary/running headlines elsewhere, correct historical subject, no cropped heads or key objects, " +
        "no unwanted text inside art, scene alignment, and the correct page number. Manuscript formulas are typeset text, not image lettering. " +
        "The deterministic PDF text comparison handles exact spelling and paragraph order; inspect visible presentation as well. " +
        "PAGINATION: pageText contains only the lines intentionally laid out on the current page. A sentence or paragraph may " +
        "start on an earlier page or continue on a later page, including a page ending mid-sentence without punctuation. " +
        "This is normal text flow, not clipping or missing content. pageFlow supplies neighbouring narrative lines and explicit " +
        "paragraph continuation flags. Neighbouring text is context only and must NOT also appear on the current page. " +
        "Full source passages attached to illustrations are scene context, not a requirement to print the entire passage on this page. " +
        "textVerification reports the completed whole-PDF comparison against the source, including extracted text and paragraph order. " +
        "When it passed, do not reject solely because a sentence is incomplete at a page boundary or its continuation is absent " +
        "from this page. For example, a page ending 'keep' followed by 'the new government stable' on the next page is valid. " +
        "Still reject actually cut-off glyphs, unreadable lines, overlap or visible loss of text that belongs to pageText. " +
        "Also check the supplied visualStyle: warm ivory paper, centred royal-blue chapter title, warm-gold chapter number, " +
        "Liberation Serif typography and dark-blue page numbers; " +
        "Reject avoidable large empty areas or a nearly empty continuation page; allow normal end-of-chapter whitespace and print-safe margins. " +
        "reject a visibly different design. Approve only when all mandatory visual/text layout checks pass. Return only the required JSON.";
}
