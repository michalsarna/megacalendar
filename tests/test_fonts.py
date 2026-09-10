"""Bundled fonts: every family must register, embed, and carry its licence text."""
from megacalendar.config import FONT_DIR
from megacalendar.pdf.fonts import available_families, register_family


def test_every_bundled_family_has_bold_and_licence():
    families = available_families()
    assert len(families) >= 14
    for family in families:
        pair = register_family(family)
        assert pair.bold == f"{family}-Bold", f"{family} has no bold face"
        licence = FONT_DIR / f"LICENSE-{family if family != 'DejaVuSans' else 'DejaVu'}.txt"
        assert licence.exists() and licence.stat().st_size > 500, f"{family} is missing its licence text"


def test_no_stray_font_files():
    stems = {p.stem for p in FONT_DIR.glob("*.ttf")}
    for stem in stems:
        base = stem.removesuffix("-Bold")
        assert base in stems, f"{stem}.ttf has no regular face {base}.ttf"
