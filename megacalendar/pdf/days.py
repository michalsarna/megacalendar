"""Decides how each day looks: background and, where overridden, text colours."""
from __future__ import annotations

from datetime import date

import holidays

from .spec import CalendarSpec, Color, DayStyle


def build_holidays(spec: CalendarSpec) -> set[date]:
    if not spec.holidays_enabled or not spec.holiday_country:
        return set()
    try:
        hol = holidays.country_holidays(
            spec.holiday_country, subdiv=spec.holiday_subdiv or None, years=spec.year
        )
    except (NotImplementedError, KeyError) as exc:
        raise ValueError(f"holidays unavailable for {spec.holiday_country!r}: {exc}") from exc
    return set(hol.keys())


def _as_style(value: DayStyle | Color | None) -> DayStyle:
    return value if isinstance(value, DayStyle) else DayStyle(background=value)


class DayClassifier:
    """Precedence: private holiday (explicit override) > public holiday > weekend > weekday."""

    def __init__(self, spec: CalendarSpec):
        self.spec = spec
        self.holidays = build_holidays(spec)
        self.overrides: dict[date, DayStyle] = {d: _as_style(v) for d, v in spec.day_overrides.items()}

    def is_holiday(self, d: date) -> bool:
        return d in self.holidays

    def background(self, d: date) -> Color | None:
        if d in self.overrides:
            return self.overrides[d].background
        if d in self.holidays and self.spec.holiday_color is not None:
            return self.spec.holiday_color
        if d.weekday() >= 5:
            return self.spec.weekend_color
        return self.spec.weekday_color

    def day_number_color(self, d: date) -> Color:
        override = self.overrides.get(d)
        if override is not None and override.day_number_color is not None:
            return override.day_number_color
        if d in self.holidays and self.spec.holiday_day_number_color is not None:
            return self.spec.holiday_day_number_color
        return self.spec.day_number_color

    def day_name_color(self, d: date) -> Color:
        override = self.overrides.get(d)
        if override is not None and override.day_name_color is not None:
            return override.day_name_color
        if d in self.holidays and self.spec.holiday_day_name_color is not None:
            return self.spec.holiday_day_name_color
        return self.spec.day_name_color

    def legend_entries(self) -> list[tuple[date, DayStyle]]:
        items = self.overrides.items()
        if self.spec.month is not None:
            items = [(d, s) for d, s in items if d.month == self.spec.month]
        return sorted(items)
