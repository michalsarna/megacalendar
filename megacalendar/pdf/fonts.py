"""TrueType font discovery and registration. Every font used is embedded in the PDF."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from ..config import FONT_DIR


@dataclass(frozen=True)
class FontPair:
    regular: str
    bold: str


def available_families(font_dir: Path = FONT_DIR) -> list[str]:
    """Font families are `<Family>.ttf` with an optional `<Family>-Bold.ttf`."""
    families = sorted(
        p.stem for p in font_dir.glob("*.ttf") if not p.stem.endswith("-Bold")
    )
    return families


def register_family(family: str, font_dir: Path = FONT_DIR) -> FontPair:
    regular_path = font_dir / f"{family}.ttf"
    if not regular_path.exists():
        raise ValueError(f"font family {family!r} not found in {font_dir}")
    bold_path = font_dir / f"{family}-Bold.ttf"

    registered = set(pdfmetrics.getRegisteredFontNames())
    if family not in registered:
        pdfmetrics.registerFont(TTFont(family, str(regular_path)))
    bold_name = family
    if bold_path.exists():
        bold_name = f"{family}-Bold"
        if bold_name not in registered:
            pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
    pdfmetrics.registerFontFamily(family, normal=family, bold=bold_name, italic=family, boldItalic=bold_name)
    return FontPair(regular=family, bold=bold_name)
