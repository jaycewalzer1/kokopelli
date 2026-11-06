"""The time windows of a life. Windows come from the calendar, so a future node can be named before it exists."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache

from settings import LIFE_DEPTH_BY_SALIENCE, LIFE_DISPLAY_HUBS, LIFE_STAGES

LEVELS = ("life", "year", "season", "month", "week", "day", "hour", "min15", "min5", "min1", "sec30")
SEASONS = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
           6: "Summer", 7: "Summer", 8: "Summer", 9: "Fall", 10: "Fall", 11: "Fall"}
FIRST_AGE, LAST_AGE = 2, 30
SCHOOL_MONTH = 9


@dataclass(frozen=True)
class Window:
    level: str
    label: str
    start: datetime
    end: datetime
    parent_id: str | None
    index: int

    @property
    def id(self):
        return f"{self.level}:{self.start.isoformat()}"

    @property
    def is_finest(self):
        return self.level == LEVELS[-1]


def depth(level):
    return LEVELS.index(level)


def depth_limit_for(salience):
    return next(level for threshold, level in LIFE_DEPTH_BY_SALIENCE if salience >= threshold)


def age_at(birth, moment):
    return (moment - datetime(birth.year, birth.month, birth.day)).total_seconds() / (365.25 * 86400)


def stage_at(age):
    return next((stage for stage in LIFE_STAGES if age < stage["until_age"]), LIFE_STAGES[-1])


def hub_at(age):
    """Which display hub a year starting at this age sits under, as an index."""
    return next(index for index, hub in enumerate(LIFE_DISPLAY_HUBS) if age < hub["until_age"])


def _birthday(birth, age):
    # Someone born on February 29 has their birthday on the 28th in other years.
    day = 28 if (birth.month, birth.day) == (2, 29) else birth.day
    return datetime(birth.year + age, birth.month, day)


def life_window(birth):
    return Window("life", "Life", _birthday(birth, FIRST_AGE), _birthday(birth, LAST_AGE), None, 0)


def _year_spans(birth):
    # Kindergarten starts the first September the child is already 5.
    kindergarten = datetime(birth.year + 5, SCHOOL_MONTH, 1)
    if _birthday(birth, 5) > kindergarten:
        kindergarten = kindergarten.replace(year=kindergarten.year + 1)
    for age in range(FIRST_AGE, LAST_AGE):
        start = _birthday(birth, age)
        if start >= kindergarten:
            break
        yield f"Age {age}", start, min(_birthday(birth, age + 1), kindergarten)

    school = ["Kindergarten", *(f"Grade {grade}" for grade in range(1, 13)), *(f"College {y}" for y in range(1, 5))]
    start = kindergarten
    for label in school:
        end = start.replace(year=start.year + 1)
        yield label, start, end
        start = end

    final, postgrad = _birthday(birth, LAST_AGE), 1
    while start < final:
        end = min(start.replace(year=start.year + 1), final)
        yield f"Postgrad {postgrad}", start, end
        start, postgrad = end, postgrad + 1


def _months(window, keep=lambda month: True):
    year, month = window.start.year, window.start.month
    while (moment := datetime(year, month, 1)) < window.end:
        if moment > window.start and keep(month):
            yield moment
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _midnights(window, keep=lambda moment: True):
    moment = datetime.combine(window.start.date(), datetime.min.time()) + timedelta(days=1)
    while moment < window.end:
        if keep(moment):
            yield moment
        moment += timedelta(days=1)


def _every(window, step):
    moment = window.start + step
    while moment < window.end:
        yield moment
        moment += step


def _slice(parent, level, cuts, label):
    edges = [parent.start, *cuts, parent.end]
    return [Window(level, label(start), start, end, parent.id, index)
            for index, (start, end) in enumerate(zip(edges, edges[1:]))]


@lru_cache(maxsize=4096)
def children(window, birth):
    """The windows that exactly cover this one, in order. Weeks are cut at month boundaries."""
    if window.level == "life":
        return [Window("year", label, start, end, window.id, index)
                for index, (label, start, end) in enumerate(_year_spans(birth))]
    if window.level == "year":
        cuts = _months(window, keep=lambda month: month in (3, 6, 9, 12))
        return _slice(window, "season", cuts, lambda s: f"{SEASONS[s.month]} {s.year}")
    if window.level == "season":
        return _slice(window, "month", _months(window), lambda s: s.strftime("%B %Y"))
    if window.level == "month":
        cuts = _midnights(window, keep=lambda moment: moment.weekday() == 0)
        return _slice(window, "week", cuts, lambda s: s.strftime("Week of %b %d"))
    if window.level == "week":
        return _slice(window, "day", _midnights(window), lambda s: s.strftime("%a %b %d %Y"))
    if window.level == "day":
        return _slice(window, "hour", _every(window, timedelta(hours=1)), lambda s: s.strftime("%H:00"))
    if window.level == "hour":
        return _slice(window, "min15", _every(window, timedelta(minutes=15)), lambda s: s.strftime("%H:%M"))
    if window.level == "min15":
        return _slice(window, "min5", _every(window, timedelta(minutes=5)), lambda s: s.strftime("%H:%M"))
    if window.level == "min5":
        return _slice(window, "min1", _every(window, timedelta(minutes=1)), lambda s: s.strftime("%H:%M"))
    if window.level == "min1":
        return _slice(window, "sec30", _every(window, timedelta(seconds=30)), lambda s: s.strftime("%H:%M:%S"))
    return []


def find(node_id, birth):
    """The window with this id, found by walking down from the top of the life."""
    level, _, start = node_id.partition(":")
    if level not in LEVELS:
        raise KeyError(node_id)
    start = datetime.fromisoformat(start)
    window = life_window(birth)
    while window.level != level:
        window = next((child for child in children(window, birth) if child.start <= start < child.end), None)
        if window is None:
            raise KeyError(node_id)
    if window.id != node_id:
        raise KeyError(node_id)
    return window
