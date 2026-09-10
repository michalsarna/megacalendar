"""Pydantic models: validation for both the JSON API and the HTML forms."""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from typing import Annotated, Any

import holidays
from babel import Locale, UnknownLocaleError, localedata
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from . import config
from .pdf.fonts import available_families
from .pdf.pagesizes import ORIENTATIONS, PAGE_SIZES
from .pdf.spec import COLOR_MODES, DAY_ALIGNS, LAYOUTS, RGB, TITLE_ALIGNS, color_from_dict, to_mode

BACKGROUND_MODES = ("cover", "contain", "stretch")


class CMYKModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    c: float = Field(0, ge=0, le=100)
    m: float = Field(0, ge=0, le=100)
    y: float = Field(0, ge=0, le=100)
    k: float = Field(0, ge=0, le=100)


class RGBModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)


def _coerce_color(v: Any) -> Any:
    """Accept "#rrggbb" strings in addition to RGB/CMYK objects."""
    if isinstance(v, str):
        return RGB.from_hex(v).to_dict()
    return v


ColorModel = Annotated[CMYKModel | RGBModel, BeforeValidator(_coerce_color)]

TEXT_COLOR_KEYS = ("title_color", "month_name_color", "day_name_color", "day_number_color", "week_number_color")
OPTIONAL_COLOR_KEYS = ("weekday_color", "weekend_color", "holiday_color", "month_border_color", "day_border_color",
                       "holiday_day_number_color", "holiday_day_name_color", "year_color")
COLOR_KEYS = TEXT_COLOR_KEYS + OPTIONAL_COLOR_KEYS

# Defaults applied when a colour key is absent from the input, per colour model.
DEFAULT_COLORS: dict[str, dict[str, dict | None]] = {
    "RGB": {
        **{key: {"r": 0, "g": 0, "b": 0} for key in TEXT_COLOR_KEYS},
        "weekday_color": None,
        "weekend_color": {"r": 224, "g": 224, "b": 224},
        "holiday_color": {"r": 229, "g": 57, "b": 53},
        "month_border_color": None,
        "day_border_color": None,
        "holiday_day_number_color": None,
        "holiday_day_name_color": None,
        "year_color": None,
    },
    "CMYK": {
        **{key: {"c": 0, "m": 0, "y": 0, "k": 100} for key in TEXT_COLOR_KEYS},
        "weekday_color": None,
        "weekend_color": {"c": 0, "m": 0, "y": 0, "k": 12},
        "holiday_color": {"c": 0, "m": 90, "y": 80, "k": 0},
        "month_border_color": None,
        "day_border_color": None,
        "holiday_day_number_color": None,
        "holiday_day_name_color": None,
        "year_color": None,
    },
}


@lru_cache(maxsize=1)
def country_choices() -> list[str]:
    """English country names (ISO 3166 territories only, no regions like 'World')."""
    territories = Locale.parse("en").territories
    names = [name for code, name in territories.items() if len(code) == 2 and code.isalpha() and code not in ("ZZ", "QO", "EU", "EZ", "UN")]
    return sorted(set(names))


@lru_cache(maxsize=1)
def language_choices() -> list[tuple[str, str]]:
    """(locale id, display name) for every language Babel knows, without territory variants."""
    out = []
    for ident in localedata.locale_identifiers():
        if "_" in ident:
            continue
        try:
            name = Locale.parse(ident).get_display_name("en")
        except (UnknownLocaleError, ValueError):
            continue
        if name:
            out.append((ident, f"{name} ({ident})"))
    return sorted(out, key=lambda t: t[1].lower())


def convert_color_model(color: CMYKModel | RGBModel, mode: str) -> CMYKModel | RGBModel:
    converted = to_mode(color_from_dict(color.model_dump()), mode)
    return RGBModel(**converted.to_dict()) if mode == "RGB" else CMYKModel(**converted.to_dict())


class ProjectBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    year: int = Field(ge=1900, le=2200)
    title: str | None = Field(default=None, max_length=200)

    page_size: str = "A1"
    orientation: str = "portrait"
    margin_mm: float = Field(default=config.DEFAULT_MARGIN_MM, ge=0, le=config.MAX_MARGIN_MM)
    locale: str = Field(default=config.DEFAULT_LOCALE, min_length=2, max_length=20)
    week_start: int = Field(default=0, ge=0, le=6)
    font_family: str = config.DEFAULT_FONT_FAMILY
    show_week_numbers: bool = False
    show_title: bool = True
    title_align: str = "center"
    show_year: bool = False
    year_align: str = "center"
    year_color: ColorModel | None = None
    layout: str = "grid"
    month_names_uppercase: bool = False
    day_names_uppercase: bool = False
    day_number_scale: float = Field(default=100, ge=10, le=300)
    day_number_align: str = "center"
    title_font: str | None = None
    title_scale: float = Field(default=100, ge=25, le=300)
    year_font: str | None = None
    year_scale: float = Field(default=100, ge=25, le=300)
    month_name_font: str | None = None
    month_name_scale: float = Field(default=100, ge=25, le=300)
    day_name_font: str | None = None
    day_name_scale: float = Field(default=100, ge=25, le=300)
    day_number_font: str | None = None
    week_number_scale: float = Field(default=100, ge=25, le=300)
    legend_font: str | None = None
    legend_scale: float = Field(default=100, ge=25, le=300)
    table_day_names: bool = True
    month_gap_mm: float | None = Field(default=None, ge=0, le=500)
    show_legend: bool = False

    color_mode: str = "RGB"
    title_color: ColorModel = RGBModel(r=0, g=0, b=0)
    month_name_color: ColorModel = RGBModel(r=0, g=0, b=0)
    day_name_color: ColorModel = RGBModel(r=0, g=0, b=0)
    day_number_color: ColorModel = RGBModel(r=0, g=0, b=0)
    week_number_color: ColorModel = RGBModel(r=0, g=0, b=0)
    weekday_color: ColorModel | None = None
    weekend_color: ColorModel | None = None
    holiday_color: ColorModel | None = None

    month_border_color: ColorModel | None = None
    month_border_width_mm: float = Field(default=0.5, ge=0.1, le=5)
    day_border_color: ColorModel | None = None
    day_border_width_mm: float = Field(default=0.2, ge=0.1, le=3)

    holidays_enabled: bool = False
    holiday_country: str | None = None
    holiday_subdiv: str | None = None
    holiday_day_number_color: ColorModel | None = None
    holiday_day_name_color: ColorModel | None = None

    background_asset_id: int | None = None  # reference into the background library
    background_mode: str = "cover"
    background_opacity: float = Field(default=100, ge=0, le=100)

    logo_asset_id: int | None = None  # library file shown in the title band
    logo_align: str = "right"
    logo_opacity: float = Field(default=100, ge=0, le=100)

    @model_validator(mode="before")
    @classmethod
    def _fill_color_defaults(cls, data):
        if not isinstance(data, dict):
            return data
        mode = str(data.get("color_mode") or "RGB").upper()
        for key, value in DEFAULT_COLORS.get(mode, {}).items():
            if key not in data:
                data[key] = value
        return data

    @field_validator("color_mode", mode="before")
    @classmethod
    def _color_mode(cls, v):
        v = str(v).upper()
        if v not in COLOR_MODES:
            raise ValueError(f"color_mode must be one of {COLOR_MODES}")
        return v

    @model_validator(mode="after")
    def _normalise_colors(self):
        """Store every colour in the project's colour model (converts on mode switch)."""
        for key in COLOR_KEYS:
            value = getattr(self, key)
            if value is not None:
                setattr(self, key, convert_color_model(value, self.color_mode))
        return self

    @field_validator("page_size")
    @classmethod
    def _page_size(cls, v: str) -> str:
        if v not in PAGE_SIZES:
            raise ValueError(f"page_size must be one of {sorted(PAGE_SIZES)}")
        return v

    @field_validator("orientation")
    @classmethod
    def _orientation(cls, v: str) -> str:
        if v not in ORIENTATIONS:
            raise ValueError(f"orientation must be one of {ORIENTATIONS}")
        return v

    @field_validator("layout")
    @classmethod
    def _layout(cls, v: str) -> str:
        if v not in LAYOUTS:
            raise ValueError(f"layout must be one of {LAYOUTS}")
        return v

    @field_validator("day_number_align")
    @classmethod
    def _day_align(cls, v: str) -> str:
        if v not in DAY_ALIGNS:
            raise ValueError(f"day_number_align must be one of {DAY_ALIGNS}")
        return v

    @field_validator("title_align", "year_align", "logo_align")
    @classmethod
    def _title_align(cls, v: str) -> str:
        if v not in TITLE_ALIGNS:
            raise ValueError(f"alignment must be one of {TITLE_ALIGNS}")
        return v

    @field_validator("locale")
    @classmethod
    def _locale(cls, v: str) -> str:
        try:
            Locale.parse(v)
        except (UnknownLocaleError, ValueError) as exc:
            raise ValueError(f"unknown language/locale {v!r}") from exc
        return v

    @model_validator(mode="after")
    def _logo_position_free(self):
        if self.logo_asset_id is not None:
            taken = {self.title_align} | ({self.year_align} if self.title and self.show_year else set())
            if self.logo_align in taken:
                free = [a for a in TITLE_ALIGNS if a not in taken]
                raise ValueError(f"logo_align {self.logo_align!r} is taken by the title/year; choose one of {free}")
        return self

    @model_validator(mode="after")
    def _month_gap_fits(self):
        if self.month_gap_mm is not None:
            from .pdf.render import max_month_gap_mm
            from .pdf.spec import CalendarSpec

            limit = max_month_gap_mm(CalendarSpec(year=self.year, page_size=self.page_size, orientation=self.orientation,
                                                  margin_mm=self.margin_mm, layout=self.layout))
            if self.month_gap_mm > limit:
                raise ValueError(f"month_gap_mm must not exceed {limit} mm for {self.page_size} {self.orientation} {self.layout}")
        return self

    @field_validator("background_mode")
    @classmethod
    def _bg_mode(cls, v: str) -> str:
        if v not in BACKGROUND_MODES:
            raise ValueError(f"background_mode must be one of {BACKGROUND_MODES}")
        return v

    @field_validator("font_family", "title_font", "year_font", "month_name_font", "day_name_font", "day_number_font",
                     "legend_font", mode="before")  # week_number_font intentionally omitted — week numbers share day_number_font
    @classmethod
    def _font(cls, v, info):
        if v is None or (isinstance(v, str) and not v.strip()):
            if info.field_name == "font_family":
                raise ValueError("font_family is required")
            return None
        if v not in available_families():
            raise ValueError(f"unknown font family {v!r}; available: {available_families()}")
        return v

    @field_validator("holiday_country", "holiday_subdiv", "title", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @model_validator(mode="after")
    def _holidays(self):
        if self.holidays_enabled:
            if not self.holiday_country:
                raise ValueError("holiday_country is required when holidays are enabled")
            supported = holidays.list_supported_countries()
            if self.holiday_country not in supported:
                raise ValueError(f"unsupported holiday country {self.holiday_country!r}")
            if self.holiday_subdiv and self.holiday_subdiv not in supported[self.holiday_country]:
                raise ValueError(f"unknown subdivision {self.holiday_subdiv!r} for {self.holiday_country}")
        return self


PROJECT_KINDS = ("year", "month")


MONTH_CALENDAR_DEFAULTS = {"page_size": "A4", "day_number_scale": 50, "day_number_align": "left", "month_name_scale": 50, "week_number_scale": 50}


class ProjectCreate(ProjectBase):
    kind: str = "year"
    month: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="before")
    @classmethod
    def _month_defaults(cls, data):
        """One-month calendars start as A4 planners: small day numbers in the top-left corner.
        Absent/blank values fall back to the kind's defaults instead of failing validation."""
        if isinstance(data, dict):
            for key in MONTH_CALENDAR_DEFAULTS:
                if data.get(key) in (None, ""):
                    data.pop(key, None)
            if data.get("kind") == "month":
                for key, value in MONTH_CALENDAR_DEFAULTS.items():
                    data.setdefault(key, value)
        return data

    @model_validator(mode="after")
    def _kind_month(self):
        if self.kind not in PROJECT_KINDS:
            raise ValueError(f"kind must be one of {PROJECT_KINDS}")
        if self.kind == "month" and self.month is None:
            raise ValueError("a one-month calendar needs a month (1-12)")
        if self.kind == "year":
            self.month = None
        return self


class ProjectUpdate(ProjectBase):
    """Kind, month and year of an existing project cannot be changed."""


class DayOverrideIn(BaseModel):
    color: ColorModel | None = None  # background; None = explicitly no background
    day_number_color: ColorModel | None = None  # None = inherit
    day_name_color: ColorModel | None = None  # None = inherit
    note: str | None = Field(default=None, max_length=200)


class DayOverrideRead(DayOverrideIn):
    model_config = ConfigDict(from_attributes=True)
    day: date


class BackgroundAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    original_name: str
    suffix: str
    size_bytes: int
    width: int | None
    height: int | None
    created_at: datetime


class ProjectRead(ProjectBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    month: int | None
    background: BackgroundAssetRead | None = None
    logo: BackgroundAssetRead | None = None
    created_at: datetime
    updated_at: datetime
    day_overrides: list[DayOverrideRead] = []


# ---------------------------------------------------------------- users & profile

class AddressIn(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    recipient: str = Field(min_length=1, max_length=200)
    street: str = Field(min_length=1, max_length=200)
    postal_code: str = Field(min_length=1, max_length=20)
    city: str = Field(min_length=1, max_length=100)
    country: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    is_default: bool = False

    @field_validator("label", "phone", mode="before")
    @classmethod
    def _blank(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


class AddressRead(AddressIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)
    locale: str = config.DEFAULT_LOCALE  # default language of new calendars

    @field_validator("locale")
    @classmethod
    def _locale(cls, v: str) -> str:
        try:
            Locale.parse(v)
        except (UnknownLocaleError, ValueError) as exc:
            raise ValueError(f"unknown language/locale {v!r}") from exc
        return v

    @field_validator("first_name", "last_name", "phone", "email", mode="before")
    @classmethod
    def _blank(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v is not None and ("@" not in v or v.startswith("@") or v.endswith("@")):
            raise ValueError("email address must contain a name and a domain")
        return v


MIN_PASSWORD = 8


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=200)


class UserCreate(ProfileUpdate):
    username: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=MIN_PASSWORD, max_length=200)
    project_limit: int | None = Field(default=1, ge=0)  # year calendars; None = unlimited
    small_project_limit: int | None = Field(default=2, ge=0)  # one-month calendars; None = unlimited
    # contact details are mandatory when an account is created
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=3, max_length=50)
    email: str = Field(min_length=3, max_length=200)


class RegisterIn(UserCreate):
    """Self-registration: fixed allowances, contact details required (inherited)."""
    project_limit: int | None = Field(default=1, frozen=True)
    small_project_limit: int | None = Field(default=2, frozen=True)


class UserUpdate(ProfileUpdate):
    project_limit: int | None = Field(default=1, ge=0)
    small_project_limit: int | None = Field(default=2, ge=0)
    is_active: bool = True
    password: str | None = Field(default=None, min_length=MIN_PASSWORD, max_length=200)  # set to reset


class UserRead(ProfileUpdate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    is_master: bool
    is_active: bool
    project_limit: int | None
    small_project_limit: int | None
    created_at: datetime
    project_count: int = 0
    small_project_count: int = 0
    addresses: list[AddressRead] = []


class MeRead(UserRead):
    csrf_token: str | None = None  # send as X-CSRF-Token with session-authenticated changes


class LoginIn(BaseModel):
    username: str
    password: str


CODE_LENGTH = 7
CODE_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def _validate_code(v: str) -> str:
    v = v.strip().upper()
    if len(v) != CODE_LENGTH or not CODE_ALPHABET.issuperset(v):
        raise ValueError(f"code must be {CODE_LENGTH} letters/digits")
    return v


class ConfirmEmailIn(BaseModel):
    code: str = Field(min_length=CODE_LENGTH, max_length=CODE_LENGTH)

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        return _validate_code(v)


class ForgotPasswordIn(BaseModel):
    identifier: str = Field(min_length=1, max_length=200)  # username or email


class ResetPasswordIn(BaseModel):
    identifier: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=CODE_LENGTH, max_length=CODE_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=200)

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        return _validate_code(v)


class MailSettingsUpdate(BaseModel):
    host: str | None = Field(default=None, max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255)  # blank = keep the one already saved
    use_tls: bool = True
    from_email: str | None = Field(default=None, max_length=200)
    from_name: str | None = Field(default=None, max_length=200)

    @field_validator("host", "username", "from_email", "from_name", mode="before")
    @classmethod
    def _blank(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("from_email")
    @classmethod
    def _email(cls, v):
        if v is not None and ("@" not in v or v.startswith("@") or v.endswith("@")):
            raise ValueError("from address must contain a name and a domain")
        return v


class MailSettingsRead(BaseModel):
    host: str | None
    port: int
    username: str | None
    use_tls: bool
    from_email: str | None
    from_name: str | None
    password_set: bool = False  # the password itself is never sent back to the browser


class Meta(BaseModel):
    page_sizes: dict[str, dict[str, float]]
    color_modes: list[str]
    layouts: list[str]
    title_aligns: list[str]
    orientations: list[str]
    background_modes: list[str]
    fonts: list[str]
    max_margin_mm: float
    holiday_countries: dict[str, list[str]]
