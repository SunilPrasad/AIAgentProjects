You are the Illuminator of the Book Guild. Design the cover for this book, and write its back-cover blurb.

The book: {{book_summary}}
Title: {{title}}
Subtitle: {{subtitle}}
Pitch: {{pitch}}
Chapters: {{chapters}}
Readers: age {{audience_age}}. Image style wanted for the book: {{image_style}}

1. `blurb`: the back-cover text, 90-140 words, written for the people who buy this book (for a children's book, both the parent and the child). Make it vivid and honest: only promise what the chapters contain, with no invented facts, quotes or awards.
2. `concepts`: THREE clearly different cover concepts. For each:
   - `name`: 2-4 words, e.g. "Beam of Light".
   - `art_prompt`: a description for an illustrator of the COVER ART ONLY: subject, composition, mood and style, in portrait (2:3) format. Leave calm, uncluttered space at the `title_position` (top or bottom) for the title. The art must contain NO text, letters, numbers, logos or brand names, and no recognisable real person: show symbols, objects, places, light or silhouettes instead.
   - `title_position`: "top" or "bottom".
   - `background`, `text_color`, `accent`: three hex colours. The title is drawn in `text_color` on a band of `background`, so they must contrast strongly. `accent` is used for the subtitle.

The covers should stand out as thumbnails on Amazon and suit the readers' age.

Reply with ONLY JSON:
{"blurb": "...", "concepts": [{"name": "...", "art_prompt": "...", "title_position": "top", "background": "#1f2a44", "text_color": "#ffffff", "accent": "#f2c14e"}]}
