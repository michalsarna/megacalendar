from datetime import date

from megacalendar.pdf.days import DayClassifier
from megacalendar.pdf.spec import CMYK, CalendarSpec

GREEN = CMYK(60, 0, 100, 0)


def make(**kw) -> CalendarSpec:
    base = dict(year=2027, weekend_color=CMYK(k=12), holiday_color=CMYK(m=90, y=80))
    base.update(kw)
    return CalendarSpec(**base)


def test_weekdays_get_no_background_by_default():
    cl = DayClassifier(make())
    assert cl.background(date(2027, 3, 15)) is None  # Monday


def test_weekends_get_gray():
    cl = DayClassifier(make())
    assert cl.background(date(2027, 3, 13)) == CMYK(k=12)  # Saturday
    assert cl.background(date(2027, 3, 14)) == CMYK(k=12)  # Sunday


def test_holidays_only_when_enabled():
    off = DayClassifier(make(holiday_country="PL"))
    assert off.background(date(2027, 1, 6)) is None  # Epiphany, Wednesday
    on = DayClassifier(make(holidays_enabled=True, holiday_country="PL"))
    assert on.background(date(2027, 1, 6)) == CMYK(m=90, y=80)


def test_holiday_beats_weekend():
    cl = DayClassifier(make(holidays_enabled=True, holiday_country="PL"))
    assert cl.background(date(2027, 5, 1)) == CMYK(m=90, y=80)  # Saturday + Labour Day


def test_override_beats_everything_including_explicit_none():
    cl = DayClassifier(
        make(holidays_enabled=True, holiday_country="PL",
             day_overrides={date(2027, 5, 1): None, date(2027, 3, 15): GREEN})
    )
    assert cl.background(date(2027, 5, 1)) is None
    assert cl.background(date(2027, 3, 15)) == GREEN


def test_weekday_color_when_set():
    cl = DayClassifier(make(weekday_color=CMYK(c=5)))
    assert cl.background(date(2027, 3, 15)) == CMYK(c=5)


def test_unknown_country_raises():
    import pytest

    with pytest.raises(ValueError):
        DayClassifier(make(holidays_enabled=True, holiday_country="XX"))


def test_holiday_and_private_holiday_text_colours():
    from megacalendar.pdf.spec import DayStyle

    red, blue, white = CMYK(0, 100, 100, 0), CMYK(100, 100, 0, 0), CMYK(0, 0, 0, 0)
    cl = DayClassifier(make(holidays_enabled=True, holiday_country="PL", holiday_day_number_color=red,
                            day_overrides={date(2027, 3, 15): DayStyle(background=None, day_number_color=white, note="x"),
                                           date(2027, 3, 16): GREEN}))
    # public holiday: number recoloured, name inherits the default
    assert cl.day_number_color(date(2027, 1, 6)) == red and cl.day_name_color(date(2027, 1, 6)) == cl.spec.day_name_color
    # private holiday: its own number colour, explicit no background, name inherits
    assert cl.background(date(2027, 3, 15)) is None and cl.day_number_color(date(2027, 3, 15)) == white
    assert cl.day_name_color(date(2027, 3, 15)) == cl.spec.day_name_color
    # bare colour override still works and inherits text colours
    assert cl.background(date(2027, 3, 16)) == GREEN and cl.day_number_color(date(2027, 3, 16)) == cl.spec.day_number_color
    # ordinary day
    assert cl.day_number_color(date(2027, 3, 17)) == cl.spec.day_number_color
    assert [d for d, _ in cl.legend_entries()] == [date(2027, 3, 15), date(2027, 3, 16)]
    # private holiday with a holiday name colour set on the project but overridden per day
    cl2 = DayClassifier(make(holidays_enabled=True, holiday_country="PL", holiday_day_name_color=blue,
                             day_overrides={date(2027, 1, 6): DayStyle(day_name_color=white)}))
    assert cl2.day_name_color(date(2027, 1, 6)) == white and cl2.day_name_color(date(2027, 5, 1)) == blue
