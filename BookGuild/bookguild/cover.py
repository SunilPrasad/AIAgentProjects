"""The cover: its settings, KDP geometry and rendering (typography is drawn by the app, not the AI).

KDP paperback cover = ONE image:  bleed | back | spine | front | bleed
    bleed        0.125" on every outside edge
    spine width  pages × 0.002252" (white paper) or × 0.0025" (cream)
    spine text   only allowed with more than 79 pages
    barcode      KDP prints it on the back: keep a 2" × 1.2" box bottom-right clear

The AI only paints text-free art (models misspell titles); the app draws the title, subtitle,
author, blurb and spine text itself, at 300 dpi.

Files:
    cover/cover.json      settings, concepts, your choice, approval
    cover/concepts/*.png  concept art
    cover/front-art.*     front art you uploaded; cover/back-art.* likewise
    cover/wrap.png/.pdf   the KDP paperback cover (exact size, 300 dpi)
    cover/ebook.jpg       the Kindle eBook cover (front only, 2560 px tall)
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

from bookguild.chapters import read_file, word_count
from bookguild.images import SLOT_APPROVED, load_slots
from bookguild.profile import BookProfile
from bookguild.storage import Book

COVER_FILE = "cover/cover.json"
DPI = 300
BLEED_IN = 0.125
SAFE_IN = 0.375  # keep text this far inside the trim (KDP asks for at least 0.125")
SPINE_TEXT_MIN_PAGES = 80
SPINE_MARGIN_IN = 0.0625
BARCODE_IN = (2.0, 1.2)
PAPER_THICKNESS_IN = {"white": 0.002252, "cream": 0.0025}
FRONT_MATTER_PAGES = 6  # title page, copyright, contents, credits…
KDP_MIN_PAGES = 24
EBOOK_HEIGHT = 2560


@dataclass
class CoverConcept:
    id: str  # "A", "B", "C"
    name: str
    art_prompt: str
    background: str = "#1f2a44"
    text_color: str = "#ffffff"
    accent: str = "#f2c14e"
    title_position: str = "top"  # where the art leaves calm space for the title
    art_file: str = ""  # relative to the book folder
    model: str = ""
    reviews: list[dict] = field(default_factory=list)


@dataclass
class CoverSpec:
    title: str = ""
    subtitle: str = ""
    author: str = ""
    blurb: str = ""
    front_art: str = ""  # relative path of the chosen concept art or your upload
    back_art: str = ""
    art_has_text: bool = False  # your uploaded art already shows the title → don't draw it again
    background: str = "#1f2a44"
    text_color: str = "#ffffff"
    accent: str = "#f2c14e"
    title_position: str = "top"
    page_count: int = 0  # 0 = estimate from the chapters
    concepts: list[CoverConcept] = field(default_factory=list)
    chosen: str = ""
    approved: bool = False


def load_cover(book: Book) -> CoverSpec | None:
    path = book.folder / COVER_FILE
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    concepts = [CoverConcept(**c) for c in data.pop("concepts", [])]
    return CoverSpec(**data, concepts=concepts)


def save_cover(book: Book, spec: CoverSpec) -> None:
    path = book.folder / COVER_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(asdict(spec), indent=1, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


# ---------- geometry ----------

def trim_inches(profile: BookProfile) -> tuple[float, float]:
    width, height = profile.trim_size.split("x")
    return float(width), float(height)


def estimate_pages(book: Book, profile: BookProfile, chapters: int) -> int:
    """Pages from the chapters - written ones by their words, unwritten ones at the planned length -
    plus front matter and images. Even, at least 24 (KDP's minimum)."""
    if chapters == 0:
        text_pages = profile.target_pages
    else:
        words = 0
        for number in range(1, chapters + 1):
            written = word_count(read_file(book, number, "final.md"))
            words += written or profile.words_per_chapter
        text_pages = words / max(1, profile.words_per_page)
    image_pages = 0.5 * sum(1 for s in load_slots(book) if s.status == SLOT_APPROVED)
    pages = math.ceil(text_pages + image_pages + FRONT_MATTER_PAGES)
    return max(KDP_MIN_PAGES, pages + pages % 2)


def spine_width_in(pages: int, paper: str) -> float:
    return pages * PAPER_THICKNESS_IN.get(paper, PAPER_THICKNESS_IN["white"])


def wrap_size_in(profile: BookProfile, pages: int) -> tuple[float, float]:
    trim_w, trim_h = trim_inches(profile)
    return 2 * BLEED_IN + 2 * trim_w + spine_width_in(pages, profile.paper), 2 * BLEED_IN + trim_h


# ---------- rendering ----------

FONT_DIRS = (Path("C:/Windows/Fonts"),)
FONT_FILES = ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "segoeui.ttf", "segoeuib.ttf", "seguisb.ttf")
_fonts_registered = False


def ensure_fonts() -> None:
    """Register the cover fonts with Qt explicitly. Without this, rendering in a background/offscreen
    Qt session drew every letter as an empty box (seen in testing) - a print file must never
    depend on how the app was started."""
    global _fonts_registered
    if _fonts_registered:
        return
    from PySide6.QtGui import QFontDatabase

    for folder in FONT_DIRS:
        for name in FONT_FILES:
            if (folder / name).exists():
                QFontDatabase.addApplicationFont(str(folder / name))
    _fonts_registered = True

def render_wrap(book: Book, spec: CoverSpec, profile: BookProfile, pages: int, guides: bool = False,
                scale: float = 1.0) -> QImage:
    """The full KDP cover at 300 dpi. `guides` draws trim/spine/barcode lines (preview only);
    `scale` < 1 renders a smaller, faster preview of exactly the same design."""
    ensure_fonts()
    trim_w, trim_h = trim_inches(profile)
    spine = spine_width_in(pages, profile.paper)
    width_in, height_in = wrap_size_in(profile, pages)
    image = QImage(round(width_in * DPI * scale), round(height_in * DPI * scale), QImage.Format.Format_RGB32)
    image.fill(QColor(spec.background))
    px = lambda inches: inches * DPI  # noqa: E731 - tiny local helper

    back = QRectF(0, 0, px(BLEED_IN + trim_w), px(height_in))
    spine_rect = QRectF(px(BLEED_IN + trim_w), 0, px(spine), px(height_in))
    front = QRectF(px(BLEED_IN + trim_w + spine), 0, px(trim_w + BLEED_IN), px(height_in))
    front_trim = QRectF(front.left(), px(BLEED_IN), px(trim_w), px(trim_h))
    back_trim = QRectF(px(BLEED_IN), px(BLEED_IN), px(trim_w), px(trim_h))

    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing |
                           QPainter.RenderHint.SmoothPixmapTransform)
    painter.scale(scale, scale)  # all drawing below is in 300-dpi units
    _draw_front(painter, book, spec, front, front_trim)
    _draw_back(painter, book, spec, back, back_trim)
    _draw_spine(painter, spec, spine_rect, pages)
    if guides:
        _draw_guides(painter, back_trim, front_trim, spine_rect, back)
    painter.end()
    return image


def render_front(book: Book, spec: CoverSpec, profile: BookProfile) -> QImage:
    """The front cover only, trimmed (no bleed) - for the eBook."""
    ensure_fonts()
    trim_w, trim_h = trim_inches(profile)
    image = QImage(round(trim_w * DPI), round(trim_h * DPI), QImage.Format.Format_RGB32)
    image.fill(QColor(spec.background))
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing |
                           QPainter.RenderHint.SmoothPixmapTransform)
    area = QRectF(0, 0, image.width(), image.height())
    _draw_front(painter, book, spec, area, area)
    painter.end()
    return image


def export_cover(book: Book, spec: CoverSpec, profile: BookProfile, pages: int) -> dict[str, str]:
    """Write cover/wrap.png, cover/wrap.pdf (exact KDP size) and cover/ebook.jpg. Returns their paths."""
    folder = book.folder / "cover"
    folder.mkdir(parents=True, exist_ok=True)
    wrap = render_wrap(book, spec, profile, pages)
    wrap.save(str(folder / "wrap.png"))

    width_in, height_in = wrap_size_in(profile, pages)
    pdf = QPdfWriter(str(folder / "wrap.pdf"))
    pdf.setResolution(DPI)
    pdf.setPageLayout(QPageLayout(QPageSize(QSizeF(width_in, height_in), QPageSize.Unit.Inch),
                                  QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0)))
    pdf.setTitle(spec.title)
    painter = QPainter(pdf)
    painter.drawImage(QRectF(0, 0, wrap.width(), wrap.height()), wrap)
    painter.end()

    front = render_front(book, spec, profile)
    ebook = front.scaledToHeight(EBOOK_HEIGHT, Qt.TransformationMode.SmoothTransformation)
    ebook.save(str(folder / "ebook.jpg"), "JPG", 92)
    return {"wrap_png": str(folder / "wrap.png"), "wrap_pdf": str(folder / "wrap.pdf"),
            "ebook": str(folder / "ebook.jpg")}


def _draw_art(painter: QPainter, image: QImage, area: QRectF) -> None:
    """Draw `image` to cover `area` completely (cropping the overflow), like CSS background-size: cover."""
    scale = max(area.width() / image.width(), area.height() / image.height())
    w, h = image.width() * scale, image.height() * scale
    painter.save()
    painter.setClipRect(area)
    painter.drawImage(QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h), image)
    painter.restore()


def _draw_front(painter: QPainter, book: Book, spec: CoverSpec, area: QRectF, trim: QRectF) -> None:
    art = QImage(str(book.folder / spec.front_art)) if spec.front_art else QImage()
    if not art.isNull():
        _draw_art(painter, art, area)
    if spec.art_has_text:
        return
    safe = trim.adjusted(SAFE_IN * DPI, SAFE_IN * DPI, -SAFE_IN * DPI, -SAFE_IN * DPI)
    title_band_height = trim.height() * 0.32
    on_top = spec.title_position != "bottom"
    band = QRectF(area.left(), area.top() if on_top else area.bottom() - title_band_height - BLEED_IN * DPI,
                  area.width(), title_band_height + BLEED_IN * DPI)
    if not art.isNull():
        _shade(painter, band, spec.background, fade_down=on_top)

    title_box = QRectF(safe.left(), safe.top() if on_top else band.top() + BLEED_IN * DPI, safe.width(),
                       title_band_height * 0.68)
    _fit_text(painter, spec.title, title_box, "Georgia", QFont.Weight.Bold, spec.text_color, max_pt=60)
    if spec.subtitle:
        subtitle_box = QRectF(safe.left(), title_box.bottom(), safe.width(), title_band_height * 0.26)
        _fit_text(painter, spec.subtitle, subtitle_box, "Georgia", QFont.Weight.Normal, spec.accent, max_pt=22,
                  italic=True)
    if spec.author:
        author_band = QRectF(area.left(), area.bottom() - trim.height() * 0.11 - BLEED_IN * DPI if on_top
                             else area.top(), area.width(), trim.height() * 0.11 + BLEED_IN * DPI)
        if not art.isNull():
            _shade(painter, author_band, spec.background, fade_down=not on_top)
        author_box = QRectF(safe.left(), safe.bottom() - trim.height() * 0.07 if on_top else safe.top(),
                            safe.width(), trim.height() * 0.07)
        _fit_text(painter, spec.author.upper(), author_box, "Segoe UI", QFont.Weight.DemiBold, spec.text_color,
                  max_pt=20, letter_spacing=2)


def _draw_back(painter: QPainter, book: Book, spec: CoverSpec, area: QRectF, trim: QRectF) -> None:
    art = QImage(str(book.folder / spec.back_art)) if spec.back_art else QImage()
    if not art.isNull():
        _draw_art(painter, art, area)
        overlay = QColor(spec.background)
        overlay.setAlphaF(0.55)
        painter.fillRect(area, overlay)
    safe = trim.adjusted(SAFE_IN * DPI, SAFE_IN * DPI, -SAFE_IN * DPI, -SAFE_IN * DPI)
    barcode_top = trim.bottom() - (0.25 + BARCODE_IN[1]) * DPI
    blurb_box = QRectF(safe.left(), safe.top() + 0.4 * DPI, safe.width(), barcode_top - safe.top() - 0.8 * DPI)
    if spec.blurb:
        _fit_text(painter, spec.blurb, blurb_box, "Georgia", QFont.Weight.Normal, spec.text_color, max_pt=14,
                  align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)


def _draw_spine(painter: QPainter, spec: CoverSpec, rect: QRectF, pages: int) -> None:
    painter.fillRect(rect, QColor(spec.background))
    if pages < SPINE_TEXT_MIN_PAGES:
        return  # KDP doesn't allow spine text on thin books
    usable = rect.width() - 2 * SPINE_MARGIN_IN * DPI
    text = f"{spec.title}   ·   {spec.author}" if spec.author else spec.title
    painter.save()
    painter.translate(rect.center())
    painter.rotate(90)  # reads top to bottom, as on English-language spines
    box = QRectF(-rect.height() / 2 + 0.4 * DPI, -usable / 2, rect.height() - 0.8 * DPI, usable)
    _fit_text(painter, text, box, "Segoe UI", QFont.Weight.DemiBold, spec.text_color, max_pt=16, single_line=True)
    painter.restore()


def _draw_guides(painter: QPainter, back_trim: QRectF, front_trim: QRectF, spine: QRectF, back: QRectF) -> None:
    painter.save()
    painter.setPen(QPen(QColor(255, 0, 80), 4, Qt.PenStyle.DashLine))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for rect in (back_trim, front_trim):
        painter.drawRect(rect)
    painter.drawLine(spine.topLeft(), spine.bottomLeft())
    painter.drawLine(spine.topRight(), spine.bottomRight())
    painter.setPen(QPen(QColor(0, 200, 255), 4, Qt.PenStyle.DotLine))
    barcode = QRectF(back_trim.right() - (0.25 + BARCODE_IN[0]) * DPI, back_trim.bottom() - (0.25 + BARCODE_IN[1]) * DPI,
                     BARCODE_IN[0] * DPI, BARCODE_IN[1] * DPI)
    painter.drawRect(barcode)
    painter.drawText(barcode, Qt.AlignmentFlag.AlignCenter, "barcode area")
    painter.restore()


def _shade(painter: QPainter, band: QRectF, color: str, fade_down: bool) -> None:
    """A soft colour band behind text so it stays readable on busy art."""
    solid, clear = QColor(color), QColor(color)
    solid.setAlphaF(0.82)
    clear.setAlphaF(0.0)
    gradient = QLinearGradient(band.topLeft(), band.bottomLeft())
    gradient.setColorAt(0.0, solid if fade_down else clear)
    gradient.setColorAt(0.7, solid)
    gradient.setColorAt(1.0, clear if fade_down else solid)
    painter.fillRect(band, gradient)


def _fit_text(painter: QPainter, text: str, box: QRectF, family: str, weight: QFont.Weight, color: str,
              max_pt: int, italic: bool = False, letter_spacing: float = 0, single_line: bool = False,
              align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter) -> None:
    """Draw text as large as fits in `box` (wrapping words), up to `max_pt` points at 300 dpi."""
    flags = align | (Qt.TextFlag.TextSingleLine if single_line else Qt.TextFlag.TextWordWrap)
    font = QFont(family)
    font.setWeight(weight)
    font.setItalic(italic)
    if letter_spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    size = max_pt
    while size > 6:
        font.setPixelSize(round(size * DPI / 72))
        painter.setFont(font)
        needed = painter.boundingRect(box, flags, text)
        if needed.height() <= box.height() and needed.width() <= box.width():
            break
        size -= 1
    painter.setPen(QColor(color))
    painter.drawText(box, flags, text)
