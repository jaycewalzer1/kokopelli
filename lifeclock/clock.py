"""The clock. Time is one integer: minutes since the world epoch.

Every level above the minute is an interval on that integer. Two shapes are
worth keeping straight:

  * Narrative levels (life, segment) are authored and end where the story says.
  * Calendar levels (year, season, month, week, day, hour) are computed.

The calendar is not a clean tree. Weeks cross months and years, winter crosses
New Year, and a birthday falls mid-year. So levels are intervals joined by time,
with `parent_key` meaning only "the span holding my start".
"""
from datetime import date, datetime, timedelta

EPOCH = date(1900, 1, 1)
EPOCH_ORD = EPOCH.toordinal()
MINUTES_PER_DAY = 1440

CALENDAR_LEVELS = ("year", "season", "month", "week", "day")
ROLLUP_LEVELS = ("life", "segment", "year", "season", "month", "week", "day")

SEASON_BY_MONTH = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "fall", 10: "fall", 11: "fall",
}


def date_to_t(d):
    return (d.toordinal() - EPOCH_ORD) * MINUTES_PER_DAY


def to_t(iso):
    """Parse YYYY-MM-DD or YYYY-MM-DDTHH:MM to minutes since the epoch."""
    if "T" in iso:
        dt = datetime.fromisoformat(iso)
        return date_to_t(dt.date()) + dt.hour * 60 + dt.minute
    return date_to_t(date.fromisoformat(iso))


def from_t(t):
    days, minutes = divmod(t, MINUTES_PER_DAY)
    d = date.fromordinal(EPOCH_ORD + days)
    return datetime(d.year, d.month, d.day, minutes // 60, minutes % 60)


def format_t(t):
    return from_t(t).strftime("%Y-%m-%dT%H:%M")


def season_key(d):
    # Winter belongs to the year it begins in, so Jan 1942 is in 1941-winter.
    year = d.year - 1 if d.month in (1, 2) else d.year
    return f"{year}-{SEASON_BY_MONTH[d.month]}"


def season_bounds(d):
    name = SEASON_BY_MONTH[d.month]
    if name == "winter":
        y = d.year - 1 if d.month in (1, 2) else d.year
        return date(y, 12, 1), date(y + 1, 3, 1)
    first = {"spring": 3, "summer": 6, "fall": 9}[name]
    return date(d.year, first, 1), date(d.year, first + 3, 1)


def month_bounds(d):
    end = date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
    return date(d.year, d.month, 1), end


def week_key(d):
    iso = d.isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


def week_bounds(d):
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=7)


def level_key(level, d):
    if level == "year":
        return f"{d.year:04d}"
    if level == "season":
        return season_key(d)
    if level == "month":
        return f"{d.year:04d}-{d.month:02d}"
    if level == "week":
        return week_key(d)
    if level == "day":
        return d.isoformat()
    raise ValueError(level)


def level_bounds(level, d):
    """Half-open [start, end) in minutes for the calendar span containing d."""
    if level == "year":
        lo, hi = date(d.year, 1, 1), date(d.year + 1, 1, 1)
    elif level == "season":
        lo, hi = season_bounds(d)
    elif level == "month":
        lo, hi = month_bounds(d)
    elif level == "week":
        lo, hi = week_bounds(d)
    elif level == "day":
        lo, hi = d, d + timedelta(days=1)
    else:
        raise ValueError(level)
    return date_to_t(lo), date_to_t(hi)
