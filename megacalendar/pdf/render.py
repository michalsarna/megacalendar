"""Lays out a whole year on one sheet and draws it with ReportLab.

Two layouts:
  grid    - 12 month blocks (3x4 portrait, 4x3 landscape), each a classic week grid
  columns - one column per month, days as rows from the 1st (portrait: two bands of six
            months, landscape: twelve columns side by side)
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import date
from typing import BinaryIO

from babel.dates import format_date, get_day_names, get_month_names
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas

from ..config import MAX_MARGIN_MM
from .background import artwork_size, draw_artwork, draw_background
from .days import DayClassifier
from .fonts import FontPair, register_family
from .pagesizes import get_page_size
from .spec import COLOR_MODES, DAY_ALIGNS, LAYOUTS, TITLE_ALIGNS, CalendarSpec, DayStyle

MAX_GAP_SHARE = 0.5  # month gaps may use at most this share of the available width/height
DAY_ROWS = 6  # grid layout: every month fits in 6 weeks; fixed so all months align
COLUMN_ROWS = 31  # columns layout: one row per possible day of month
WEEK_COL_RATIO = 0.7  # width of the week-number column relative to a day cell


@dataclass(frozen=True)
class Frame:
    """Page geometry shared by both layouts."""

    page_w: float
    page_h: float
    margin: float
    title_h: float
    gutter_x: float
    gutter_y: float
    band_gap: float  # space between the title band / legend and the month blocks
    footer_h: float  # strip at the very bottom for the watermark
    legend_h: float = 0.0  # reserved at the bottom (0 = no legend)

    @property
    def content_w(self) -> float:
        return self.page_w - 2 * self.margin

    @property
    def content_h(self) -> float:
        return self.page_h - 2 * self.margin

    @property
    def grid_top(self) -> float:
        return self.page_h - self.margin - self.title_h - self.band_gap

    @property
    def grid_bottom(self) -> float:
        return self.margin + self.footer_h + (self.legend_h + self.band_gap if self.legend_h else 0.0)

    @property
    def grid_h(self) -> float:
        return self.grid_top - self.grid_bottom


def blocks_for(spec: CalendarSpec) -> tuple[int, int]:
    """(columns, rows) of month blocks for the layout/orientation."""
    if spec.month is not None:
        return (1, 1)
    if spec.layout == "grid":
        return (3, 4) if spec.orientation == "portrait" else (4, 3)
    return (6, 2) if spec.orientation == "portrait" else (12, 1)


def max_month_gap_mm(spec: CalendarSpec) -> float:
    """Largest gap between months that still leaves every month block at least half the sheet."""
    page_w, page_h = get_page_size(spec.page_size).points(spec.orientation)
    margin = spec.margin_mm * mm
    content_w, content_h = page_w - 2 * margin, page_h - 2 * margin
    header = content_h * (0.07 + 0.025) if spec.show_title else 0.0
    grid_h = content_h - header - content_h * 0.012  # minus title band + gap, footer
    cols, rows = blocks_for(spec)
    limits = [content_w * MAX_GAP_SHARE / (cols - 1)] if cols > 1 else []
    if rows > 1:
        limits.append(grid_h * MAX_GAP_SHARE / (rows - 1))
    return round(min(limits) / mm, 1) if limits else 0.0


def compute_frame(spec: CalendarSpec) -> Frame:
    if spec.margin_mm > MAX_MARGIN_MM:
        raise ValueError(f"margin {spec.margin_mm}mm exceeds the {MAX_MARGIN_MM}mm print limit")
    page_w, page_h = get_page_size(spec.page_size).points(spec.orientation)
    margin = spec.margin_mm * mm
    content_w, content_h = page_w - 2 * margin, page_h - 2 * margin
    if spec.month_gap_mm is None:
        # automatic: month grids breathe, table-style columns touch each other
        gutter_x = content_w * 0.03 if spec.layout == "grid" else 0.0
        gutter_y = content_h * 0.025 if spec.layout == "grid" else 0.0
    else:
        limit = max_month_gap_mm(spec)
        if spec.month_gap_mm < 0 or spec.month_gap_mm > limit:
            raise ValueError(f"month gap must be between 0 and {limit} mm for this sheet and layout")
        gutter_x = gutter_y = spec.month_gap_mm * mm
    title_h, band_gap = (content_h * 0.07, content_h * 0.025) if spec.show_title else (0.0, 0.0)
    return Frame(page_w, page_h, margin, title_h=title_h, gutter_x=gutter_x, gutter_y=gutter_y,
                 band_gap=band_gap, footer_h=content_h * 0.012)


WATERMARK = "Made with megacalendar"


def _draw_watermark(c: Canvas, spec: CalendarSpec, frame: Frame, fonts: FontSet) -> None:
    """Small light-grey credit in the bottom-right corner, inside the printable area."""
    from .spec import CMYK, RGB

    grey = CMYK(0, 0, 0, 35) if spec.color_mode == "CMYK" else RGB(170, 170, 170)
    size = frame.footer_h * 0.6
    c.setFillColor(spec.paint(grey))
    c.setFont(fonts.base.regular, size)
    c.drawRightString(frame.page_w - frame.margin, baseline_for_vcenter(fonts.base.regular, size, frame.margin, frame.footer_h),
                      WATERMARK)


# ---------------------------------------------------------------- fonts per element

@dataclass(frozen=True)
class FontSet:
    base: FontPair
    title: FontPair
    year: FontPair
    month: FontPair
    day_name: FontPair
    day_number: FontPair
    legend: FontPair


def resolve_fonts(spec: CalendarSpec) -> FontSet:
    base = register_family(spec.font_family)
    pick = lambda family: register_family(family) if family else base  # noqa: E731
    return FontSet(base=base, title=pick(spec.title_font), year=pick(spec.year_font), month=pick(spec.month_name_font),
                   day_name=pick(spec.day_name_font), day_number=pick(spec.day_number_font), legend=pick(spec.legend_font))


def scaled(size: float, percent: float, cap: float) -> float:
    """Apply a user percentage to an automatic size without letting text overflow its box."""
    return min(size * percent / 100, cap)


# ---------------------------------------------------------------- text helpers

def fit_font_size(text: str, font: str, max_size: float, max_width: float) -> float:
    width = pdfmetrics.stringWidth(text, font, max_size)
    if width <= max_width or width == 0:
        return max_size
    return max_size * max_width / width


def baseline_for_vcenter(font: str, size: float, y: float, h: float) -> float:
    ascent, descent = pdfmetrics.getAscentDescent(font, size)
    return y + (h - (ascent - descent)) / 2 - descent


def _draw_centered(c: Canvas, text: str, font: str, size: float, x: float, y: float, w: float, h: float) -> None:
    c.setFont(font, size)
    c.drawCentredString(x + w / 2, baseline_for_vcenter(font, size, y, h), text)


def _day_number_baseline(font: str, size: float, cy: float, cell_w: float, cell_h: float, align: str) -> float:
    """Baseline for a day/week number: vertically centred for "center", top corner (planner
    style) otherwise. Shared by day and week numbers so they always line up on the same row."""
    if align == "center":
        return baseline_for_vcenter(font, size, cy, cell_h)
    pad = min(cell_w, cell_h) * 0.08
    ascent, _ = pdfmetrics.getAscentDescent(font, size)
    return cy + cell_h - pad - ascent


def shared_font_size(labels, font: str, max_size: float, max_width: float) -> float:
    """One size that fits every label, so e.g. all month headers match."""
    return min(fit_font_size(label, font, max_size, max_width) for label in labels)


def calendar_names(spec: CalendarSpec) -> tuple[dict[int, str], dict[int, str]]:
    """Localised month names (1-12) and weekday abbreviations keyed by date.weekday() (0 = Monday)."""
    month_names = dict(get_month_names("wide", context="stand-alone", locale=spec.locale))
    day_names = dict(get_day_names("abbreviated", context="stand-alone", locale=spec.locale))
    if spec.month_names_uppercase:
        month_names = {k: v.upper() for k, v in month_names.items()}
    if spec.day_names_uppercase:
        day_names = {k: v.upper() for k, v in day_names.items()}
    return month_names, day_names


# ---------------------------------------------------------------- title band: title, year, logo

LOGO_MAX_WIDTH_SHARE = 0.3  # of the content width


def title_band_positions(spec: CalendarSpec) -> set[str]:
    """Alignments occupied by text in the title band."""
    used = {spec.title_align}
    if spec.title and spec.show_year:
        used.add(spec.year_align)
    return used


def logo_box(spec: CalendarSpec, frame: Frame) -> tuple[float, float, float, float] | None:
    """(x, y, w, h) of the logo: as tall as the title band, aspect preserved, width capped."""
    if spec.logo_path is None:
        return None
    if spec.logo_align not in TITLE_ALIGNS:
        raise ValueError(f"unknown logo alignment {spec.logo_align!r}; choose one of {TITLE_ALIGNS}")
    if spec.logo_align in title_band_positions(spec):
        raise ValueError(f"logo position {spec.logo_align!r} is taken by the title or year; choose another")
    src_w, src_h = artwork_size(spec.logo_path)
    h = frame.title_h
    w = h * src_w / src_h
    max_w = frame.content_w * LOGO_MAX_WIDTH_SHARE
    if w > max_w:
        w, h = max_w, max_w * src_h / src_w
    band_y = frame.page_h - frame.margin - frame.title_h
    y = band_y + (frame.title_h - h) / 2
    if spec.logo_align == "left":
        x = frame.margin
    elif spec.logo_align == "right":
        x = frame.page_w - frame.margin - w
    else:
        x = frame.page_w / 2 - w / 2
    return x, y, w, h


def _draw_logo(c: Canvas, spec: CalendarSpec, box: tuple[float, float, float, float], font_name: str) -> None:
    x, y, w, h = box
    draw_artwork(c, spec.logo_path, x, y, w, h, "contain", font_name, spec.color_mode, spec.logo_opacity / 100)


def _draw_aligned(c: Canvas, text: str, font: str, size: float, align: str, frame: Frame, y: float, h: float) -> None:
    c.setFont(font, size)
    baseline = baseline_for_vcenter(font, size, y, h)
    if align == "left":
        c.drawString(frame.margin, baseline, text)
    elif align == "right":
        c.drawRightString(frame.page_w - frame.margin, baseline, text)
    else:
        c.drawCentredString(frame.page_w / 2, baseline, text)


def _draw_title(c: Canvas, spec: CalendarSpec, frame: Frame, fonts: FontSet, reserved_w: float = 0.0) -> None:
    """reserved_w: width taken by the logo (plus a gap), which the text must not run into."""
    band_y = frame.page_h - frame.margin - frame.title_h
    avail_w = frame.content_w - reserved_w
    title_font, year_font = fonts.title.bold, fonts.year.regular
    c.setFillColor(spec.paint(spec.title_color))
    title = spec.display_title
    if not (spec.title and spec.show_year):
        # Without a custom title the "title" is the year: use the year's font and size when set.
        font, scale = (year_font, spec.year_scale) if not spec.title else (title_font, spec.title_scale)
        size = fit_font_size(title, font, scaled(frame.title_h * 0.8, scale, frame.title_h * 0.95), avail_w)
        _draw_aligned(c, title, font, size, spec.title_align, frame, band_y, frame.title_h)
        return
    year = str(spec.year)
    year_color = spec.paint(spec.year_color or spec.title_color)
    if spec.year_align == spec.title_align:
        # Same corner: year goes under the title.
        title_h, year_h = frame.title_h * 0.62, frame.title_h * 0.38
        size = fit_font_size(title, title_font, scaled(title_h * 0.8, spec.title_scale, title_h * 0.95), avail_w)
        _draw_aligned(c, title, title_font, size, spec.title_align, frame, band_y + year_h, title_h)
        c.setFillColor(year_color)
        year_size = fit_font_size(year, year_font, scaled(year_h * 0.8, spec.year_scale, year_h * 0.95), avail_w)
        _draw_aligned(c, year, year_font, year_size, spec.year_align, frame, band_y, year_h)
    else:
        # Different corners: side by side on one line, year a little smaller.
        year_size = scaled(frame.title_h * 0.5, spec.year_scale, frame.title_h * 0.95)
        year_w = pdfmetrics.stringWidth(year, year_font, year_size)
        size = fit_font_size(title, title_font, scaled(frame.title_h * 0.8, spec.title_scale, frame.title_h * 0.95),
                             avail_w - year_w - frame.content_w * 0.04)
        _draw_aligned(c, title, title_font, size, spec.title_align, frame, band_y, frame.title_h)
        c.setFillColor(year_color)
        _draw_aligned(c, year, year_font, year_size, spec.year_align, frame, band_y, frame.title_h)


# ---------------------------------------------------------------- grid layout

def _draw_month_grid(
    c: Canvas, spec: CalendarSpec, fonts: FontSet, classifier: DayClassifier, month: int,
    x: float, y_top: float, month_w: float, month_h: float, month_names: dict[int, str], day_names: dict[int, str],
    name_size: float, num_rows: int = DAY_ROWS,
) -> None:
    header_h = month_h * 0.14
    dow_h = month_h * 0.08
    cell_h = (month_h - header_h - dow_h) / num_rows
    week_ratio = WEEK_COL_RATIO if spec.show_week_numbers else 0.0
    cell_w = month_w / (7 + week_ratio)
    week_w = cell_w * week_ratio
    ordered_days = [day_names[(spec.week_start + i) % 7] for i in range(7)]

    # Month name
    c.setFillColor(spec.paint(spec.month_name_color))
    _draw_centered(c, month_names[month], fonts.month.bold, name_size, x, y_top - header_h, month_w, header_h)

    # Weekday abbreviations
    c.setFillColor(spec.paint(spec.day_name_color))
    dow_size = scaled(dow_h * 0.5, spec.day_name_scale, dow_h * 0.9)
    for label in ordered_days:
        dow_size = min(dow_size, fit_font_size(label, fonts.day_name.regular, dow_size, cell_w * 0.9))
    dow_y = y_top - header_h - dow_h
    for i, label in enumerate(ordered_days):
        _draw_centered(c, label, fonts.day_name.regular, dow_size, x + week_w + i * cell_w, dow_y, cell_w, dow_h)

    # Day cells
    weeks = calendar.Calendar(firstweekday=spec.week_start).monthdatescalendar(spec.year, month)
    day_size = scaled(min(cell_h * 0.45, cell_w * 0.5), spec.day_number_scale, cell_h * 0.9)
    week_size = scaled(min(cell_h * 0.45, cell_w * 0.5) * 0.55, spec.week_number_scale, cell_h * 0.9)
    day_font = fonts.day_number.regular
    for r in range(min(num_rows, len(weeks))):
        cy = dow_y - (r + 1) * cell_h
        week = weeks[r]
        in_month = [d for d in week if d.month == month]
        if not in_month:
            continue
        if spec.show_week_numbers:
            c.setFillColor(spec.paint(spec.week_number_color))
            week_baseline = _day_number_baseline(day_font, week_size, cy, cell_w, cell_h, spec.day_number_align)
            c.setFont(day_font, week_size)
            c.drawCentredString(x + week_w / 2, week_baseline, str(in_month[0].isocalendar()[1]))
        for i, d in enumerate(week):
            if d.month != month:
                continue
            cx = x + week_w + i * cell_w
            bg = classifier.background(d)
            if bg is not None:
                c.setFillColor(spec.paint(bg))
                c.rect(cx, cy, cell_w, cell_h, stroke=0, fill=1)
            c.setFillColor(spec.paint(classifier.day_number_color(d)))
            baseline = _day_number_baseline(day_font, day_size, cy, cell_w, cell_h, spec.day_number_align)
            c.setFont(day_font, day_size)
            if spec.day_number_align == "center":
                c.drawCentredString(cx + cell_w / 2, baseline, str(d.day))
            elif spec.day_number_align == "left":
                pad = min(cell_w, cell_h) * 0.08
                c.drawString(cx + pad, baseline, str(d.day))
            else:
                pad = min(cell_w, cell_h) * 0.08
                c.drawRightString(cx + cell_w - pad, baseline, str(d.day))

    # Per-day borders, after all fills so they stay visible
    if spec.day_border_color is not None:
        c.setStrokeColor(spec.paint(spec.day_border_color))
        c.setLineWidth(spec.day_border_width_mm * mm)
        c.setLineJoin(0)
        for r in range(min(num_rows, len(weeks))):
            cy = dow_y - (r + 1) * cell_h
            for i, d in enumerate(weeks[r]):
                if d.month == month:
                    c.rect(x + week_w + i * cell_w, cy, cell_w, cell_h, stroke=1, fill=0)

    _draw_border(c, spec, x, y_top - month_h, month_w, month_h)


def _draw_single_month_layout(c, spec, frame, fonts, classifier, month_names, day_names) -> None:
    """One-month calendar: the whole grid area is a single month block."""
    month_w, month_h = frame.content_w, frame.grid_h
    weeks = calendar.Calendar(firstweekday=spec.week_start).monthdatescalendar(spec.year, spec.month)
    num_rows = len(weeks)
    header_h = month_h * 0.14
    name_size = shared_font_size([month_names[spec.month]], fonts.month.bold,
                                 scaled(header_h * 0.55, spec.month_name_scale, header_h * 0.9), month_w * 0.95)
    _draw_month_grid(c, spec, fonts, classifier, spec.month, frame.margin, frame.grid_top, month_w, month_h,
                     month_names, day_names, name_size, num_rows=num_rows)


def _draw_grid_layout(c, spec, frame, fonts, classifier, month_names, day_names) -> None:
    cols, rows = blocks_for(spec)
    month_w = (frame.content_w - (cols - 1) * frame.gutter_x) / cols
    month_h = (frame.grid_h - (rows - 1) * frame.gutter_y) / rows
    header_h = month_h * 0.14
    name_size = shared_font_size(month_names.values(), fonts.month.bold,
                                 scaled(header_h * 0.55, spec.month_name_scale, header_h * 0.9), month_w * 0.95)
    for idx in range(12):
        col, row = idx % cols, idx // cols
        x = frame.margin + col * (month_w + frame.gutter_x)
        y_top = frame.grid_top - row * (month_h + frame.gutter_y)
        _draw_month_grid(c, spec, fonts, classifier, idx + 1, x, y_top, month_w, month_h, month_names, day_names, name_size)


# ---------------------------------------------------------------- columns layout

def _draw_month_column(
    c: Canvas, spec: CalendarSpec, fonts: FontSet, classifier: DayClassifier, month: int,
    x: float, y_top: float, col_w: float, band_h: float, month_names: dict[int, str], day_names: dict[int, str],
    name_size: float,
) -> None:
    header_h = band_h * 0.06
    row_h = (band_h - header_h) / COLUMN_ROWS
    pad = col_w * 0.06

    # Month name
    c.setFillColor(spec.paint(spec.month_name_color))
    _draw_centered(c, month_names[month], fonts.month.bold, name_size, x, y_top - header_h, col_w, header_h)

    num_font, dname_font = fonts.day_number.regular, fonts.day_name.regular
    base_size = min(row_h * 0.62, col_w * 0.17)
    num_size = scaled(base_size, spec.day_number_scale, row_h * 0.9)
    name_size = scaled(base_size * 0.75, spec.day_name_scale, row_h * 0.9)
    for label in day_names.values():
        name_size = min(name_size, fit_font_size(label, dname_font, name_size, col_w * 0.34))
    week_size = base_size * 0.6
    num_right = x + pad + pdfmetrics.stringWidth("00", num_font, num_size)
    name_left = num_right + col_w * 0.08
    ndays = calendar.monthrange(spec.year, month)[1]

    for i in range(ndays):
        d = date(spec.year, month, i + 1)
        cy = y_top - header_h - (i + 1) * row_h
        bg = classifier.background(d)
        if bg is not None:
            c.setFillColor(spec.paint(bg))
            c.rect(x, cy, col_w, row_h, stroke=0, fill=1)
        c.setFillColor(spec.paint(classifier.day_number_color(d)))
        c.setFont(num_font, num_size)
        c.drawRightString(num_right, baseline_for_vcenter(num_font, num_size, cy, row_h), str(d.day))
        if spec.table_day_names:
            c.setFillColor(spec.paint(classifier.day_name_color(d)))
            c.setFont(dname_font, name_size)
            c.drawString(name_left, baseline_for_vcenter(dname_font, name_size, cy, row_h), day_names[d.weekday()])
        if spec.show_week_numbers and (d.weekday() == spec.week_start or d.day == 1):
            c.setFillColor(spec.paint(spec.week_number_color))
            c.setFont(num_font, week_size)
            c.drawRightString(x + col_w - pad, baseline_for_vcenter(num_font, week_size, cy, row_h),
                              str(d.isocalendar()[1]))

    # Per-day borders, after all fills so they stay visible
    if spec.day_border_color is not None:
        c.setStrokeColor(spec.paint(spec.day_border_color))
        c.setLineWidth(spec.day_border_width_mm * mm)
        c.setLineJoin(0)
        for i in range(ndays):
            c.rect(x, y_top - header_h - (i + 1) * row_h, col_w, row_h, stroke=1, fill=0)

    _draw_border(c, spec, x, y_top - band_h, col_w, band_h)


def _draw_columns_layout(c, spec, frame, fonts, classifier, month_names, day_names) -> None:
    per_band, bands = blocks_for(spec)
    col_w = (frame.content_w - (per_band - 1) * frame.gutter_x) / per_band
    band_h = (frame.grid_h - (bands - 1) * frame.gutter_y) / bands
    header_h = band_h * 0.06
    name_size = shared_font_size(month_names.values(), fonts.month.bold,
                                 scaled(header_h * 0.55, spec.month_name_scale, header_h * 0.9), col_w * 0.9)
    for idx in range(12):
        band, col = idx // per_band, idx % per_band
        x = frame.margin + col * (col_w + frame.gutter_x)
        y_top = frame.grid_top - band * (band_h + frame.gutter_y)
        _draw_month_column(c, spec, fonts, classifier, idx + 1, x, y_top, col_w, band_h, month_names, day_names, name_size)


# ---------------------------------------------------------------- legend

@dataclass(frozen=True)
class LegendPlan:
    rows: list[list[tuple[str, DayStyle, float]]]  # (label, style, entry width)
    row_h: float
    font_size: float
    swatch: float

    @property
    def height(self) -> float:
        return len(self.rows) * self.row_h


def plan_legend(spec: CalendarSpec, frame: Frame, fonts: FontSet, classifier: DayClassifier) -> LegendPlan | None:
    entries = classifier.legend_entries() if spec.show_legend else []
    if not entries:
        return None
    font_size = scaled(frame.content_h * 0.016 * 0.6, spec.legend_scale, frame.content_h * 0.05)
    row_h = max(frame.content_h * 0.016, font_size / 0.6)  # rows grow with the font
    swatch = row_h * 0.7
    gap_between = row_h * 1.2
    rows: list[list[tuple[str, DayStyle, float]]] = [[]]
    used = 0.0
    for d, style in entries:
        label = format_date(d, format="d MMM", locale=spec.locale)
        if style.note:
            label += f" – {style.note}"
        width = swatch + row_h * 0.4 + pdfmetrics.stringWidth(label, fonts.legend.regular, font_size)
        if rows[-1] and used + gap_between + width > frame.content_w:
            rows.append([])
            used = 0.0
        rows[-1].append((label, style, width))
        used += (gap_between if len(rows[-1]) > 1 else 0.0) + width
    return LegendPlan(rows, row_h, font_size, swatch)


def _draw_legend(c: Canvas, spec: CalendarSpec, frame: Frame, fonts: FontSet, plan: LegendPlan) -> None:
    gap_between = plan.row_h * 1.2
    top = frame.margin + frame.footer_h + plan.height
    for r, row in enumerate(plan.rows):
        y = top - (r + 1) * plan.row_h
        x = frame.margin
        for label, style, width in row:
            sy = y + (plan.row_h - plan.swatch) / 2
            if style.background is not None:
                c.setFillColor(spec.paint(style.background))
                c.rect(x, sy, plan.swatch, plan.swatch, stroke=0, fill=1)
            else:  # "no background" is shown as an empty outlined box
                c.setStrokeColor(spec.paint(spec.day_number_color))
                c.setLineWidth(0.3 * mm)
                c.rect(x, sy, plan.swatch, plan.swatch, stroke=1, fill=0)
            # Labels always use the normal text colour: a day's own number colour is tuned for its cell background.
            c.setFillColor(spec.paint(spec.day_number_color))
            c.setFont(fonts.legend.regular, plan.font_size)
            c.drawString(x + plan.swatch + plan.row_h * 0.4, baseline_for_vcenter(fonts.legend.regular, plan.font_size, y, plan.row_h), label)
            x += width + gap_between


# ---------------------------------------------------------------- shared

def _draw_border(c: Canvas, spec: CalendarSpec, x: float, y: float, w: float, h: float) -> None:
    """Frame around a month block, drawn last so day backgrounds never cover it."""
    if spec.month_border_color is None:
        return
    c.setStrokeColor(spec.paint(spec.month_border_color))
    c.setLineWidth(spec.month_border_width_mm * mm)
    c.setLineJoin(0)
    c.rect(x, y, w, h, stroke=1, fill=0)


def render_calendar(spec: CalendarSpec, out: BinaryIO) -> None:
    if spec.color_mode not in COLOR_MODES:
        raise ValueError(f"unknown colour mode {spec.color_mode!r}; choose one of {COLOR_MODES}")
    if spec.layout not in LAYOUTS:
        raise ValueError(f"unknown layout {spec.layout!r}; choose one of {LAYOUTS}")
    if spec.month is not None and not 1 <= spec.month <= 12:
        raise ValueError(f"month must be 1-12, got {spec.month}")
    if spec.day_number_align not in DAY_ALIGNS:
        raise ValueError(f"unknown day number alignment {spec.day_number_align!r}; choose one of {DAY_ALIGNS}")
    if spec.title_align not in TITLE_ALIGNS or spec.year_align not in TITLE_ALIGNS:
        raise ValueError(f"unknown title alignment; choose one of {TITLE_ALIGNS}")
    frame = compute_frame(spec)
    fonts = resolve_fonts(spec)
    classifier = DayClassifier(spec)
    month_names, day_names = calendar_names(spec)
    legend = plan_legend(spec, frame, fonts, classifier)
    if legend is not None:
        frame = replace(frame, legend_h=legend.height)

    # initialFontName: otherwise ReportLab references (non-embedded) Helvetica in the page preamble.
    c = Canvas(out, pagesize=(frame.page_w, frame.page_h), initialFontName=fonts.base.regular, initialFontSize=12,
               enforceColorSpace=spec.color_mode)  # hard guarantee: a colour in the wrong model raises
    c.setTitle(f"{spec.display_title} wall calendar")
    period = f"{spec.year}-{spec.month:02d}" if spec.month else str(spec.year)
    c.setSubject(f"{spec.page_size} {spec.orientation} calendar {period}")
    c.setCreator("megacalendar")
    c.setAuthor("megacalendar")

    if spec.background_path is not None:
        draw_background(c, spec.background_path, frame.page_w, frame.page_h, spec.background_mode, fonts.base.regular,
                        spec.color_mode, spec.background_opacity / 100)

    logo = logo_box(spec, frame) if spec.show_title else None
    if spec.show_title:
        _draw_title(c, spec, frame, fonts, reserved_w=(logo[2] + frame.content_w * 0.03) if logo else 0.0)
    if logo is not None:
        _draw_logo(c, spec, logo, fonts.base.regular)
    if spec.month is not None:
        draw = _draw_single_month_layout
    else:
        draw = _draw_grid_layout if spec.layout == "grid" else _draw_columns_layout
    draw(c, spec, frame, fonts, classifier, month_names, day_names)
    if legend is not None:
        _draw_legend(c, spec, frame, fonts, legend)
    _draw_watermark(c, spec, frame, fonts)

    c.showPage()
    c.save()
