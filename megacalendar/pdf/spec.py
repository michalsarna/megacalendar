"""Data model consumed by the renderer. Independent of the database layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from reportlab.lib.colors import CMYKColor, Color as RLColor

COLOR_MODES = ("RGB", "CMYK")
DAY_ALIGNS = ("left", "center", "right")
VALIGNS = ("top", "middle", "bottom")
LAYOUTS = ("grid", "columns")
TITLE_ALIGNS = ("left", "center", "right")


@dataclass(frozen=True)
class CMYK:
    """Process colour, each channel 0-100 (percent ink coverage)."""

    c: float = 0.0
    m: float = 0.0
    y: float = 0.0
    k: float = 0.0

    def __post_init__(self) -> None:
        for name in ("c", "m", "y", "k"):
            v = getattr(self, name)
            if not 0.0 <= v <= 100.0:
                raise ValueError(f"CMYK channel {name}={v} out of range 0-100")

    def to_reportlab(self) -> CMYKColor:
        return CMYKColor(self.c / 100, self.m / 100, self.y / 100, self.k / 100)

    def to_dict(self) -> dict[str, float]:
        return {"c": self.c, "m": self.m, "y": self.y, "k": self.k}

    def to_rgb(self) -> RGB:
        k = 1 - self.k / 100
        return RGB(round(255 * (1 - self.c / 100) * k), round(255 * (1 - self.m / 100) * k), round(255 * (1 - self.y / 100) * k))

    @classmethod
    def from_dict(cls, d: dict | None) -> CMYK | None:
        if d is None:
            return None
        return cls(float(d["c"]), float(d["m"]), float(d["y"]), float(d["k"]))

    @classmethod
    def from_rgb(cls, r: float, g: float, b: float) -> CMYK:
        """Naive RGB (0-1) -> CMYK with full black generation. Good enough for
        converting vector artwork colours; photos should be supplied as CMYK."""
        k = 1.0 - max(r, g, b)
        if k >= 1.0:
            return cls(0, 0, 0, 100)
        c = (1.0 - r - k) / (1.0 - k)
        m = (1.0 - g - k) / (1.0 - k)
        y = (1.0 - b - k) / (1.0 - k)
        return cls(float(round(c * 100)), float(round(m * 100)), float(round(y * 100)), float(round(k * 100)))


@dataclass(frozen=True)
class RGB:
    """Screen colour, each channel 0-255."""

    r: int
    g: int
    b: int

    def __post_init__(self) -> None:
        for name in ("r", "g", "b"):
            v = getattr(self, name)
            if not 0 <= v <= 255:
                raise ValueError(f"RGB channel {name}={v} out of range 0-255")

    def to_reportlab(self) -> RLColor:
        return RLColor(self.r / 255, self.g / 255, self.b / 255)

    def to_dict(self) -> dict[str, int]:
        return {"r": self.r, "g": self.g, "b": self.b}

    def to_hex(self) -> str:
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    def to_cmyk(self) -> CMYK:
        return CMYK.from_rgb(self.r / 255, self.g / 255, self.b / 255)

    @classmethod
    def from_hex(cls, value: str) -> RGB:
        v = value.strip().lstrip("#")
        if len(v) == 3:
            v = "".join(ch * 2 for ch in v)
        if len(v) != 6:
            raise ValueError(f"invalid hex colour {value!r}")
        return cls(int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))

    @classmethod
    def from_dict(cls, d: dict | None) -> RGB | None:
        if d is None:
            return None
        return cls(int(d["r"]), int(d["g"]), int(d["b"]))


Color = CMYK | RGB


def color_from_dict(d: dict | None) -> Color | None:
    if d is None:
        return None
    return RGB.from_dict(d) if "r" in d else CMYK.from_dict(d)


def to_mode(color: Color, mode: str) -> Color:
    """Express a colour in the given colour model (conversion is approximate)."""
    if mode == "CMYK":
        return color if isinstance(color, CMYK) else color.to_cmyk()
    if mode == "RGB":
        return color if isinstance(color, RGB) else color.to_rgb()
    raise ValueError(f"unknown colour mode {mode!r}; choose one of {COLOR_MODES}")


BLACK = CMYK(0, 0, 0, 100)
LIGHT_GRAY = CMYK(0, 0, 0, 12)
HOLIDAY_RED = CMYK(0, 90, 80, 0)


@dataclass(frozen=True)
class DayStyle:
    """Explicit styling of one day (a "private holiday"). None = inherit."""

    background: Color | None = None
    day_number_color: Color | None = None
    day_name_color: Color | None = None
    note: str | None = None


@dataclass
class CalendarSpec:
    year: int
    month: int | None = None  # set -> a one-month calendar (single big month grid)
    page_size: str = "A1"  # key into pagesizes.PAGE_SIZES
    orientation: str = "portrait"  # portrait | landscape
    margin_mm: float = 10.0
    locale: str = "en"
    week_start: int = 0  # 0 = Monday ... 6 = Sunday
    font_family: str = "DejaVuSans"
    title: str | None = None  # defaults to the year
    show_title: bool = True  # False: no header band at all (title, year and logo), the grid uses the full height
    title_align: str = "center"  # left | center | right
    show_year: bool = False  # with a custom title: also print the year
    year_align: str = "center"  # same as title_align -> year goes under the title
    year_color: Color | None = None  # None = same as the title colour
    layout: str = "grid"  # grid | columns
    show_week_numbers: bool = False
    month_names_uppercase: bool = False
    day_names_uppercase: bool = False
    day_number_scale: float = 100.0  # percent of the automatic day-number size
    day_number_align: str = "center"  # horizontal: left | center | right
    day_number_valign: str = "middle"  # vertical: top | middle | bottom
    day_name_valign: str = "middle"  # vertical position of weekday header labels / table-style day names
    # Per-element typography. Font None = the project font_family; scales are percent of the automatic size.
    title_font: str | None = None
    title_scale: float = 100.0
    year_font: str | None = None
    year_scale: float = 100.0
    month_name_font: str | None = None
    month_name_scale: float = 100.0
    day_name_font: str | None = None
    day_name_scale: float = 100.0
    day_number_font: str | None = None
    week_number_scale: float = 100.0
    legend_font: str | None = None
    legend_scale: float = 100.0
    table_day_names: bool = True  # table layout: show the day name next to each number
    month_gap_mm: float | None = None  # space between month blocks; None = automatic
    show_legend: bool = False  # list private holidays at the bottom of the sheet

    # Output colour model. Every colour below is converted to this before drawing.
    color_mode: str = "RGB"
    title_color: Color = BLACK
    month_name_color: Color = BLACK
    day_name_color: Color = BLACK  # weekday abbreviations
    day_number_color: Color = BLACK
    week_number_color: Color = BLACK
    weekday_color: Color | None = None  # Mon-Fri background; None = paper
    weekend_color: Color | None = LIGHT_GRAY
    holiday_color: Color | None = HOLIDAY_RED

    holidays_enabled: bool = False
    holiday_country: str | None = None
    holiday_subdiv: str | None = None
    holiday_day_number_color: Color | None = None  # None = normal day-number colour
    holiday_day_name_color: Color | None = None  # None = normal day-name colour

    # Frame around each month block. None = no border.
    month_border_color: Color | None = None
    month_border_width_mm: float = 0.5
    # Table layout only: border around every day row. None = no border.
    day_border_color: Color | None = None
    day_border_width_mm: float = 0.2

    background_path: Path | None = None
    background_mode: str = "cover"  # cover | contain | stretch
    background_opacity: float = 100.0  # 0 = invisible, 100 = opaque

    # Logo in the title band, scaled to the band height. Must not share a position with title/year.
    logo_path: Path | None = None
    logo_align: str = "right"
    logo_opacity: float = 100.0

    # Private holidays: explicit per-day styling. For convenience a bare Color / None is
    # accepted as "background only" (None = explicitly no background).
    day_overrides: dict[date, DayStyle | Color | None] = field(default_factory=dict)

    @property
    def display_title(self) -> str:
        return self.title if self.title else str(self.year)

    def paint(self, color: Color):
        """ReportLab colour object in this spec's colour model."""
        return to_mode(color, self.color_mode).to_reportlab()
