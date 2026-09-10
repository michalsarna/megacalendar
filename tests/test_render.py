import io
import re
from pathlib import Path

import pytest
from PIL import Image

from megacalendar.pdf import CMYK, CalendarSpec, render_calendar
from megacalendar.pdf.spec import CMYK as C

from .helpers import assert_print_ready

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="100" height="141" viewBox="0 0 100 141">
<rect width="100" height="141" fill="#f4efe6"/><circle cx="50" cy="40" r="30" fill="rgb(20,120,200)"/></svg>"""


def render(spec: CalendarSpec) -> bytes:
    buf = io.BytesIO()
    render_calendar(spec, buf)
    return buf.getvalue()


@pytest.mark.parametrize("size,orient,w,h", [
    ("A1", "portrait", 594, 841), ("A1", "landscape", 841, 594),
    ("A0", "portrait", 841, 1189), ("A0", "landscape", 1189, 841),
])
def test_all_sheet_formats_are_print_ready(size, orient, w, h):
    pdf = render(CalendarSpec(year=2027, page_size=size, orientation=orient, show_week_numbers=True,
                              holidays_enabled=True, holiday_country="FI", locale="fi", color_mode="CMYK"))
    assert_print_ready(pdf, w, h)


@pytest.mark.parametrize("size,orient,w,h", [("A1", "portrait", 594, 841), ("A0", "landscape", 1189, 841)])
def test_rgb_mode_is_default_and_converts_cmyk_colours(size, orient, w, h):
    spec = CalendarSpec(year=2027, page_size=size, orientation=orient, month_border_color=CMYK(0, 0, 0, 60),
                        holidays_enabled=True, holiday_country="PL")
    assert spec.color_mode == "RGB"
    assert_print_ready(render(spec), w, h, mode="RGB")


@pytest.mark.parametrize("size,w,h", [("A2", 420, 594), ("A3", 297, 420), ("A4", 210, 297), ("A5", 148, 210)])
@pytest.mark.parametrize("layout", ["grid", "columns"])
def test_smaller_sheets_render_in_both_layouts(size, w, h, layout):
    spec = CalendarSpec(year=2027, page_size=size, layout=layout, show_week_numbers=True, color_mode="CMYK",
                        holidays_enabled=True, holiday_country="PL", month_border_color=CMYK(0, 0, 0, 100), margin_mm=5)
    assert_print_ready(render(spec), w, h)
    assert_print_ready(render(CalendarSpec(year=2027, page_size=size, orientation="landscape", layout=layout)), h, w, mode="RGB")


def test_margin_above_limit_rejected():
    with pytest.raises(ValueError, match="10.0mm"):
        render(CalendarSpec(year=2027, margin_mm=12))


def test_unsupported_page_size_rejected():
    with pytest.raises(ValueError, match="unsupported page size"):
        render(CalendarSpec(year=2027, page_size="A6"))


def test_svg_background_becomes_cmyk_vectors(tmp_path: Path):
    svg = tmp_path / "bg.svg"
    svg.write_text(SVG)
    pdf = render(CalendarSpec(year=2027, background_path=svg, background_mode="cover", color_mode="CMYK"))
    assert_print_ready(pdf, 594, 841, expect_images=0)
    pdf = render(CalendarSpec(year=2027, background_path=svg, background_mode="cover", color_mode="RGB"))
    assert_print_ready(pdf, 594, 841, expect_images=0, mode="RGB")


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "CMYK"])
def test_raster_background_is_embedded_as_cmyk_image(tmp_path: Path, mode):
    img = Image.new(mode, (200, 283), (200, 40, 40, 255) if mode == "RGBA" else (200, 40, 40, 0)[: len(mode)])
    path = tmp_path / ("bg.jpg" if mode == "CMYK" else "bg.png")
    img.save(path)
    pdf = render(CalendarSpec(year=2027, background_path=path, background_mode="stretch", color_mode="CMYK"))
    assert_print_ready(pdf, 594, 841, expect_images=1)
    pdf = render(CalendarSpec(year=2027, background_path=path, background_mode="stretch", color_mode="RGB"))
    assert_print_ready(pdf, 594, 841, expect_images=1, mode="RGB")


def _ext_gstates(pdf: bytes) -> list[dict]:
    from pypdf import PdfReader

    page = PdfReader(io.BytesIO(pdf)).pages[0]
    return [dict(v.get_object()) for v in page["/Resources"].get("/ExtGState", {}).values()]


def test_background_opacity_sets_constant_alpha(tmp_path: Path):
    png = tmp_path / "bg.png"
    Image.new("RGBA", (40, 60), (10, 20, 200, 128)).save(png)
    svg = tmp_path / "bg.svg"
    svg.write_text(SVG)

    opaque = render(CalendarSpec(year=2027, background_path=png))
    assert not any("/ca" in gs and gs["/ca"] != 1 for gs in _ext_gstates(opaque))

    faded = render(CalendarSpec(year=2027, background_path=png, background_opacity=35))
    assert {"/ca": 0.35} in _ext_gstates(faded)

    faded_svg = render(CalendarSpec(year=2027, background_path=svg, background_opacity=40, color_mode="CMYK"))
    assert {"/ca": 0.4} in _ext_gstates(faded_svg)
    assert_print_ready(faded_svg, 594, 841)

    invisible = render(CalendarSpec(year=2027, background_path=png, background_opacity=0))
    assert_print_ready(invisible, 594, 841, expect_images=0, mode="RGB")


def test_colour_model_conversions():
    from megacalendar.pdf.spec import RGB, to_mode

    assert RGB(255, 0, 0).to_cmyk() == CMYK(0, 100, 100, 0)
    assert CMYK(0, 0, 0, 12).to_rgb() == RGB(224, 224, 224)
    assert RGB.from_hex("#e0e0e0") == RGB(224, 224, 224) and RGB(224, 224, 224).to_hex() == "#e0e0e0"
    assert RGB.from_hex("fff") == RGB(255, 255, 255)
    assert to_mode(RGB(0, 0, 0), "CMYK") == CMYK(0, 0, 0, 100)
    assert to_mode(CMYK(0, 0, 0, 100), "RGB") == RGB(0, 0, 0)
    assert to_mode(RGB(1, 2, 3), "RGB") == RGB(1, 2, 3)
    with pytest.raises(ValueError):
        to_mode(RGB(0, 0, 0), "LAB")
    with pytest.raises(ValueError):
        render(CalendarSpec(year=2027, color_mode="LAB"))


def test_rgb_to_cmyk_black_generation():
    assert C.from_rgb(0, 0, 0) == CMYK(0, 0, 0, 100)
    assert C.from_rgb(1, 1, 1) == CMYK(0, 0, 0, 0)
    assert C.from_rgb(1, 0, 0) == CMYK(0, 100, 100, 0)
    mid = C.from_rgb(0.5, 0.5, 0.5)
    assert (mid.c, mid.m, mid.y) == (0, 0, 0) and mid.k == 50


def test_month_border_is_stroked_in_cmyk():
    from pypdf import PdfReader

    plain = render(CalendarSpec(year=2027, color_mode="CMYK"))
    bordered = render(CalendarSpec(year=2027, month_border_color=CMYK(0, 0, 0, 100), month_border_width_mm=1.0,
                                   color_mode="CMYK"))
    assert_print_ready(bordered, 594, 841)
    content = PdfReader(io.BytesIO(bordered)).pages[0].get_contents().get_data()
    assert content.count(b" re S") - PdfReader(io.BytesIO(plain)).pages[0].get_contents().get_data().count(b" re S") == 12
    assert b"0 0 0 1 K" in content
    assert re.search(rb"\n2\.83\d* w", content)  # 1 mm in points
    # Frames are drawn after the day cells so a coloured cell can never cover the line.
    assert content.rfind(b" re S") > content.rfind(b" re f")


def test_each_text_element_uses_its_own_colour():
    from pypdf import PdfReader

    spec = CalendarSpec(year=2027, color_mode="CMYK", show_week_numbers=True,
                        title_color=CMYK(10, 0, 0, 0), month_name_color=CMYK(20, 0, 0, 0), day_name_color=CMYK(30, 0, 0, 0),
                        day_number_color=CMYK(40, 0, 0, 0), week_number_color=CMYK(50, 0, 0, 0))
    content = PdfReader(io.BytesIO(render(spec))).pages[0].get_contents().get_data()
    for c in (10, 20, 30, 40, 50):
        assert f"\n.{c // 10} 0 0 0 k\n".encode() in content, c


@pytest.mark.parametrize("size,orient,w,h", [
    ("A1", "portrait", 594, 841), ("A1", "landscape", 841, 594),
    ("A0", "portrait", 841, 1189), ("A0", "landscape", 1189, 841),
])
def test_columns_layout_is_print_ready(size, orient, w, h):
    spec = CalendarSpec(year=2027, page_size=size, orientation=orient, layout="columns", show_week_numbers=True,
                        holidays_enabled=True, holiday_country="PL", locale="pl", color_mode="CMYK",
                        month_border_color=CMYK(0, 0, 0, 100), month_names_uppercase=True, day_names_uppercase=True)
    assert_print_ready(render(spec), w, h)


def test_columns_layout_draws_every_day_once():
    from pypdf import PdfReader

    spec = CalendarSpec(year=2027, layout="columns", weekend_color=None, holiday_color=None, month_border_color=None)
    text = PdfReader(io.BytesIO(render(spec))).pages[0].get_contents().get_data()
    # 365 day rows + 12 month names + 365 day names + title = 743 text objects
    assert text.count(b" Tj") == 365 + 12 + 365 + 1


def test_title_alignment_moves_the_title():
    import re as _re

    from pypdf import PdfReader

    def title_x(align):
        content = PdfReader(io.BytesIO(render(CalendarSpec(year=2027, title_align=align)))).pages[0].get_contents().get_data()
        m = _re.search(rb"BT 1 0 0 1 ([\d.]+) [\d.]+ Tm [^\n]*\(2027\) Tj", content)
        assert m, "title text object not found"
        return float(m.group(1))

    left, center, right = title_x("left"), title_x("center"), title_x("right")
    assert left < center < right
    assert abs(left - 10 * 72 / 25.4) < 0.01  # flush with the 10 mm margin
    with pytest.raises(ValueError, match="title alignment"):
        render(CalendarSpec(year=2027, title_align="justify"))
    with pytest.raises(ValueError, match="layout"):
        render(CalendarSpec(year=2027, layout="spiral"))


def test_uppercase_switches_are_independent():
    from megacalendar.pdf.render import calendar_names

    months, days = calendar_names(CalendarSpec(year=2027, locale="pl"))
    assert months[1] == "styczeń" and days[0] == "pon."
    months, days = calendar_names(CalendarSpec(year=2027, locale="pl", month_names_uppercase=True))
    assert months[1] == "STYCZEŃ" and days[0] == "pon."
    months, days = calendar_names(CalendarSpec(year=2027, locale="pl", day_names_uppercase=True))
    assert months[1] == "styczeń" and days[0] == "PON."


def _content(spec: CalendarSpec) -> bytes:
    from pypdf import PdfReader

    return PdfReader(io.BytesIO(render(spec))).pages[0].get_contents().get_data()


def _font_sizes(content: bytes) -> list[float]:
    return [float(m) for m in re.findall(rb"/F\d\+0 ([\d.]+) Tf", content)]


def test_day_number_scale_changes_font_size_in_both_layouts():
    # the most frequent size is the day-number size (365 occurrences)
    common = lambda sizes: max(set(sizes), key=sizes.count)  # noqa: E731
    base = dict(year=2027, show_week_numbers=False, table_day_names=False)  # only day numbers occur 365 times
    for layout, scale in (("grid", 150), ("columns", 120)):
        normal = _font_sizes(_content(CalendarSpec(layout=layout, **base)))
        big = _font_sizes(_content(CalendarSpec(layout=layout, day_number_scale=scale, **base)))
        assert abs(common(big) / common(normal) - scale / 100) < 0.01, layout
    # in the table layout the size is capped so numbers never overflow their row
    huge = _font_sizes(_content(CalendarSpec(layout="columns", day_number_scale=300, **base)))
    capped = _font_sizes(_content(CalendarSpec(layout="columns", day_number_scale=200, **base)))
    assert common(huge) == common(capped)


def test_table_day_names_can_be_hidden():
    spec = CalendarSpec(year=2027, layout="columns", weekend_color=None, holiday_color=None, table_day_names=False)
    assert _content(spec).count(b" Tj") == 365 + 12 + 1  # days + month names + title, no day names


def test_table_day_borders_are_stroked_after_fills():
    plain = _content(CalendarSpec(year=2027, layout="columns", color_mode="CMYK"))
    bordered = _content(CalendarSpec(year=2027, layout="columns", color_mode="CMYK",
                                     day_border_color=CMYK(0, 0, 0, 50), day_border_width_mm=0.3))
    assert bordered.count(b" re S") - plain.count(b" re S") == 365
    assert b"0 0 0 .5 K" in bordered and re.search(rb"\n\.85\d* w", bordered)  # 0.3 mm
    assert bordered.rfind(b" re S") > bordered.rfind(b" re f")
    # ignored in the grid layout
    grid = _content(CalendarSpec(year=2027, layout="grid", day_border_color=CMYK(0, 0, 0, 50)))
    assert grid.count(b" re S") == 0


def test_legend_lists_private_holidays_and_reserves_space():
    from datetime import date

    from megacalendar.pdf.spec import DayStyle

    overrides = {date(2027, 3, 15): DayStyle(background=CMYK(60, 0, 100, 0), note="Company day"),
                 date(2027, 7, 1): DayStyle(background=None, note="Inventory"),
                 date(2027, 12, 24): CMYK(0, 50, 100, 0)}
    base = dict(year=2027, color_mode="CMYK", day_overrides=overrides, weekend_color=None, holiday_color=None,
                month_border_color=CMYK(0, 0, 0, 100))
    without = _content(CalendarSpec(**base))
    with_legend = _content(CalendarSpec(show_legend=True, **base))
    assert with_legend.count(b" Tj") == without.count(b" Tj") + 3  # one label per private holiday
    assert with_legend.count(b" re S") == without.count(b" re S") + 1  # the "no background" entry is an outlined box
    assert with_legend.count(b" re f") == without.count(b" re f") + 2  # two coloured swatches
    assert_print_ready(render(CalendarSpec(show_legend=True, **base)), 594, 841)
    # month blocks move up to make room: the lowest border rectangle sits higher
    lowest = lambda content: min(float(m) for m in re.findall(rb"\nn [\d.]+ ([\d.]+) [\d.]+ [\d.]+ re S", content))  # noqa: E731
    assert lowest(with_legend) > lowest(without)
    # no private holidays -> no legend, nothing reserved
    assert _content(CalendarSpec(year=2027, show_legend=True, color_mode="CMYK")) == _content(CalendarSpec(year=2027, color_mode="CMYK"))


def test_month_gap_is_bounded_and_applied():
    from megacalendar.pdf.render import max_month_gap_mm

    a1_grid = max_month_gap_mm(CalendarSpec(year=2027))
    a1_table_landscape = max_month_gap_mm(CalendarSpec(year=2027, layout="columns", orientation="landscape"))
    assert a1_table_landscape < a1_grid  # 11 gaps must fit instead of 2
    border = dict(month_border_color=CMYK(0, 0, 0, 100), color_mode="CMYK")
    xs = lambda content: sorted({round(float(m), 2) for m in re.findall(rb"\nn ([\d.]+) [\d.]+ [\d.]+ [\d.]+ re S", content)})  # noqa: E731
    narrow = xs(_content(CalendarSpec(year=2027, month_gap_mm=2, **border)))
    wide = xs(_content(CalendarSpec(year=2027, month_gap_mm=40, **border)))
    assert narrow[0] == wide[0]  # first column starts at the margin either way
    assert narrow[1] < wide[1]  # a bigger gap pushes the second column right
    with pytest.raises(ValueError, match="month gap must be between 0 and"):
        render(CalendarSpec(year=2027, month_gap_mm=a1_grid + 1))
    render(CalendarSpec(year=2027, month_gap_mm=a1_grid))  # the limit itself is fine
    render(CalendarSpec(year=2027, month_gap_mm=0))  # touching blocks are allowed


def test_title_with_year_stacked_or_side_by_side():
    def texts(spec):
        return re.findall(rb"BT 1 0 0 1 ([\d.]+) ([\d.]+) Tm /F\d\+0 ([\d.]+) Tf [^\n]*\((Team|2027)\) Tj", _content(spec))

    plain = texts(CalendarSpec(year=2027, title="Team"))
    assert [t[3] for t in plain] == [b"Team"]  # show_year off: title only
    assert [t[3] for t in texts(CalendarSpec(year=2027, title="Team", show_year=True, title_align="left", year_align="right"))] == [b"Team", b"2027"]
    side = texts(CalendarSpec(year=2027, title="Team", show_year=True, title_align="left", year_align="right"))
    stacked = texts(CalendarSpec(year=2027, title="Team", show_year=True, title_align="left", year_align="left"))
    # side by side: year further right than the title; stacked: year below the title, both flush left
    assert float(side[1][0]) > float(side[0][0])
    assert float(stacked[1][1]) < float(stacked[0][1]) and abs(float(stacked[1][0]) - float(stacked[0][0])) < 0.01
    assert float(stacked[0][2]) > float(stacked[1][2])  # title larger than the year
    # the year can have its own colour; by default it shares the title colour
    def colour_before_year(spec):
        content = _content(spec)
        return re.findall(rb"([\d. ]+) k\nBT [^\n]*\(2027\) Tj", content)[-1]

    shared = CalendarSpec(year=2027, title="Team", show_year=True, color_mode="CMYK", title_color=CMYK(0, 0, 0, 100))
    own = CalendarSpec(year=2027, title="Team", show_year=True, color_mode="CMYK", title_color=CMYK(0, 0, 0, 100),
                       year_color=CMYK(100, 0, 0, 0))
    assert colour_before_year(shared) == b"0 0 0 1" and colour_before_year(own) == b"1 0 0 0"
    # without a custom title the year is the title and show_year changes nothing
    assert _content(CalendarSpec(year=2027, show_year=True)) == _content(CalendarSpec(year=2027))


def test_logo_scales_to_title_band_and_respects_positions(tmp_path: Path):
    from pypdf import PdfReader

    from megacalendar.pdf.render import compute_frame, logo_box

    wide = tmp_path / "wide.png"
    Image.new("RGB", (200, 100), (0, 0, 200)).save(wide)  # 2:1 fits the 30% width cap at full band height
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 400), (0, 0, 200)).save(tall)
    svg = tmp_path / "mark.svg"
    svg.write_text(SVG)

    spec = CalendarSpec(year=2027, logo_path=wide, logo_align="right", color_mode="CMYK")
    frame = compute_frame(spec)
    x, y, w, h = logo_box(spec, frame)
    assert abs(h - frame.title_h) < 1e-6 and abs(w / h - 2) < 1e-6  # full band height, aspect kept
    assert abs(x + w - (frame.page_w - frame.margin)) < 1e-6  # flush right
    x, y, w, h = logo_box(CalendarSpec(year=2027, logo_path=tall, logo_align="left"), frame)
    assert abs(h - frame.title_h) < 1e-6 and abs(x - frame.margin) < 1e-6 and abs(w / h - 0.25) < 1e-6
    # very wide artwork is capped to 30% of the content width and shrinks in height instead
    very_wide = tmp_path / "banner.png"
    Image.new("RGB", (2000, 100), (0, 0, 200)).save(very_wide)
    x, y, w, h = logo_box(CalendarSpec(year=2027, logo_path=very_wide, logo_align="left"), frame)
    assert abs(w - frame.content_w * 0.3) < 1e-6 and h < frame.title_h

    # rendered: one image in CMYK mode, the image matrix carries the box size
    pdf = render(spec)
    assert_print_ready(pdf, 594, 841, expect_images=1)
    content = PdfReader(io.BytesIO(pdf)).pages[0].get_contents().get_data()
    m = re.search(rb"q\n([\d.]+) 0 0 ([\d.]+) [\d.]+ [\d.]+ cm\n/FormXob", content)
    assert m and abs(float(m.group(2)) - frame.title_h) < 0.01

    # SVG logo: vectors, no image; opacity becomes a graphics state
    assert_print_ready(render(CalendarSpec(year=2027, logo_path=svg, logo_align="left", color_mode="CMYK")), 594, 841, expect_images=0)
    faded = render(CalendarSpec(year=2027, logo_path=svg, logo_align="left", logo_opacity=35))
    assert {"/ca": 0.35} in _ext_gstates(faded)

    # positions taken by the title (and the year when shown) are refused
    with pytest.raises(ValueError, match="taken by the title"):
        render(CalendarSpec(year=2027, logo_path=svg, logo_align="center"))
    with pytest.raises(ValueError, match="taken by the title"):
        render(CalendarSpec(year=2027, title="Team", show_year=True, title_align="left", year_align="right",
                            logo_path=svg, logo_align="right"))
    render(CalendarSpec(year=2027, title="Team", show_year=True, title_align="left", year_align="right", logo_path=svg, logo_align="center"))
    with pytest.raises(ValueError, match="unknown logo alignment"):
        render(CalendarSpec(year=2027, logo_path=svg, logo_align="top"))


def test_rgb_to_cmyk_rounds_to_whole_percent():
    from megacalendar.pdf.spec import RGB

    assert RGB(16, 32, 48).to_cmyk() == CMYK(67, 33, 0, 81)
    assert RGB(200, 200, 200).to_cmyk() == CMYK(0, 0, 0, 22)
