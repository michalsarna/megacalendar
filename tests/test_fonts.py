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


def test_per_element_fonts_and_scales_render():
    import io
    import re

    from pypdf import PdfReader

    from megacalendar.pdf import CalendarSpec, render_calendar
    from tests.helpers import assert_print_ready

    from datetime import date

    from megacalendar.pdf.spec import CMYK, DayStyle

    spec = CalendarSpec(year=2027, title="Team", show_year=True, title_align="left", year_align="right", color_mode="CMYK",
                        title_font="Oswald", year_font="Lora", month_name_font="Montserrat", day_name_font="Roboto",
                        day_number_font="NotoSans", legend_font="Merriweather", show_legend=True, layout="columns",
                        day_overrides={date(2027, 3, 15): DayStyle(background=CMYK(50, 0, 0, 0), note="Kick-off")})
    buf = io.BytesIO()
    render_calendar(spec, buf)
    pdf = buf.getvalue()
    assert_print_ready(pdf, 594, 841)
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    names = {str(f.get_object()["/BaseFont"]).split("+")[-1] for f in page["/Resources"]["/Font"].values()}
    def used(family, bold=False):  # PDF BaseFont names are the fonts' internal names, e.g. "Lora-Regular"
        return any(n.startswith(family) and (("Bold" in n) == bold) for n in names)

    assert used("Oswald", bold=True) and used("Montserrat", bold=True)
    assert used("Lora") and used("Roboto") and used("NotoSans") and used("Merriweather")
    assert any(n.startswith("DejaVu") for n in names)  # the project font is still used, only for the watermark

    def sizes(spec):
        b = io.BytesIO()
        render_calendar(spec, b)
        content = PdfReader(io.BytesIO(b.getvalue())).pages[0].get_contents().get_data()
        return re.findall(rb"BT [^\n]*?/F\d\+0 ([\d.]+) Tf [^\n]*\((Team|2027|January|Company day|Mon)\) Tj", content)

    base = dict(year=2027, title="Team", show_year=True, title_align="left", year_align="right")
    normal = {label: float(size) for size, label in sizes(CalendarSpec(**base))}
    bigger = {label: float(size) for size, label in sizes(CalendarSpec(title_scale=110, year_scale=50, **base))}
    assert abs(bigger[b"Team"] / normal[b"Team"] - 1.1) < 0.01 and abs(bigger[b"2027"] / normal[b"2027"] - 0.5) < 0.01
    # scales never push text past its box: the title is capped at 95% of the band (automatic size is 80%)
    capped = {label: float(size) for size, label in sizes(CalendarSpec(title_scale=300, **base))}
    assert abs(capped[b"Team"] / normal[b"Team"] - 0.95 / 0.8) < 0.01
