"""The Book Profile: the style sheet every agent follows (profile.json in the book folder).

The Cartographer drafts it from your brief, you edit and approve it, and every later
agent gets it in its prompt. That is how one pipeline handles a strict evidence book
for adults and a picture book for 5-year-olds.

`BookProfile.from_dict` never trusts its input: unknown values are replaced by
sensible defaults and numbers are clamped, with a warning for each fix.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields

from bookguild.storage import Book

PROFILE_FILE = "profile.json"

MODES = {
    "evidence": "Evidence-based non-fiction",
    "fiction": "Fiction",
    "children": "Children's illustrated book",
    "workbook": "Workbook / activity book",
}
VOICES = {"first": "1st person", "second": "2nd person (you)", "third": "3rd person"}
IMAGE_STRATEGIES = {
    "licensed_web": "Licensed web images",
    "ai_generated": "AI-generated images",
    "mixed": "Mixed (licensed + AI)",
    "none": "No images",
}
TRIM_SIZES = ("5x8", "5.5x8.5", "6x9", "7x10", "8x10", "8.5x8.5", "8.5x11")
PAPERS = ("white", "cream")
FORMATS = {"kdp_paperback": "KDP paperback", "kindle_ebook": "Kindle eBook", "etsy_pdf": "Etsy PDF"}

# Defaults that depend on the kind of book.
MODE_DEFAULTS = {
    "evidence": dict(citations_required=True, fact_check=True, words_per_page=250,
                     image_strategy="licensed_web", images_per_chapter=2, trim_size="6x9"),
    "fiction": dict(citations_required=False, fact_check=False, words_per_page=275,
                    image_strategy="none", images_per_chapter=0, trim_size="5.5x8.5"),
    "children": dict(citations_required=False, fact_check=False, words_per_page=50,
                     image_strategy="ai_generated", images_per_chapter=4, trim_size="8.5x8.5"),
    "workbook": dict(citations_required=False, fact_check=False, words_per_page=120,
                     image_strategy="mixed", images_per_chapter=3, trim_size="8.5x11"),
}

# (min, max) for every number field.
LIMITS = {
    "target_pages": (10, 800),
    "words_per_page": (10, 400),
    "chapter_count": (1, 60),
    "images_per_chapter": (0, 30),
    "budget_usd": (0.5, 200.0),
}


@dataclass
class BookProfile:
    working_title: str = ""
    subject: str = ""  # one-line description of what the book is about
    mode: str = "evidence"
    audience: str = "General adult readers"
    audience_age: str = "adult"  # e.g. "adult", "13-17", "6-8"
    reading_level: str = "general"
    tone: str = "clear and engaging"
    voice: str = "third"
    citations_required: bool = True
    fact_check: bool = True
    image_strategy: str = "licensed_web"
    images_per_chapter: int = 2
    image_style: str = ""
    target_pages: int = 100
    words_per_page: int = 250
    chapter_count: int = 10
    trim_size: str = "6x9"
    paper: str = "white"
    formats: list[str] = field(default_factory=lambda: list(FORMATS))
    budget_usd: float = 5.0
    must_include: list[str] = field(default_factory=list)  # topics/points the book must cover
    avoid: list[str] = field(default_factory=list)  # things to stay away from
    style_notes: str = ""  # examples and preferences taken from the brief
    approved: bool = False

    @property
    def target_words(self) -> int:
        return self.target_pages * self.words_per_page

    @property
    def words_per_chapter(self) -> int:
        return self.target_words // max(1, self.chapter_count)

    def to_dict(self) -> dict:
        return asdict(self)

    def for_prompt(self) -> str:
        """The profile as compact JSON for agent prompts (without the approval flag)."""
        data = self.to_dict()
        data.pop("approved")
        return json.dumps(data, indent=1, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> tuple[BookProfile, list[str]]:
        """Build a valid profile from untrusted data (e.g. a model's JSON). Returns (profile, warnings)."""
        warnings: list[str] = []
        if not isinstance(data, dict):
            return cls(), ["Profile data was not an object - using defaults."]

        mode = _choice(data.get("mode"), MODES, "evidence", "mode", warnings)
        values = {**asdict(cls()), **MODE_DEFAULTS[mode], "mode": mode}
        known = {f.name for f in fields(cls)}

        for name, raw in data.items():
            if name not in known or name == "mode" or raw is None:
                continue
            default = values[name]
            if name in LIMITS:
                values[name] = _clamped(raw, name, default, warnings)
            elif isinstance(default, bool):
                values[name] = _boolean(raw)
            elif isinstance(default, list):
                values[name] = _string_list(raw)
            else:
                values[name] = str(raw).strip()

        values["audience_age"] = normalize_age(values["audience_age"])
        values["voice"] = _choice(values["voice"], VOICES, "third", "voice", warnings)
        values["image_strategy"] = _choice(values["image_strategy"], IMAGE_STRATEGIES, "none",
                                           "image_strategy", warnings)
        values["trim_size"] = _choice(values["trim_size"], TRIM_SIZES, "6x9", "trim_size", warnings)
        values["paper"] = _choice(values["paper"], PAPERS, "white", "paper", warnings)
        values["formats"] = [f for f in values["formats"] if f in FORMATS] or list(FORMATS)
        if values["image_strategy"] == "none":
            values["images_per_chapter"] = 0
        return cls(**values), warnings


def load_profile(book: Book) -> BookProfile | None:
    path = book.folder / PROFILE_FILE
    if not path.exists():
        return None
    profile, _ = BookProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))
    return profile


def save_profile(book: Book, profile: BookProfile) -> None:
    path = book.folder / PROFILE_FILE
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def normalize_age(value: str) -> str:
    """'teenagers_13_17' -> '13-17', 'Adults' -> 'adult', '8+' -> '8+'. Unclear text is kept as it is."""
    text = str(value).strip().lower()
    numbers = re.findall(r"\d+", text)
    if len(numbers) >= 2:
        return f"{numbers[0]}-{numbers[1]}"
    if "adult" in text or not text:
        return "adult"
    if len(numbers) == 1:
        return f"{numbers[0]}+"
    return text


# ---------- helpers for from_dict ----------

def _choice(value, allowed, default: str, name: str, warnings: list[str]) -> str:
    text = str(value or "").strip().lower().replace('"', "")
    for candidate in (text, text.replace(" ", "_"), text.replace(" ", "")):  # "6 x 9", "licensed web"
        if candidate in allowed:
            return candidate
    if value not in (None, ""):
        warnings.append(f"Unknown {name} '{value}' - using '{default}'.")
    return default


def _clamped(value, name: str, default, warnings: list[str]):
    low, high = LIMITS[name]
    number_type = float if isinstance(default, float) else int
    try:
        number = number_type(float(value))
    except (TypeError, ValueError):
        warnings.append(f"{name} '{value}' is not a number - using {default}.")
        return default
    if not low <= number <= high:
        clamped = max(low, min(high, number))
        warnings.append(f"{name} {number} is outside {low}-{high} - using {clamped}.")
        return number_type(clamped)
    return number


def _boolean(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "on")
    return bool(value)


def _string_list(value) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
