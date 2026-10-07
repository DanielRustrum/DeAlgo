"""Format boxes: reshaping raw JSON into the bars a Chart leaflet draws.

A Format box is wired from a source box and into a Chart leaflet. What comes
in is JSON: a REST API source's last whole answer, or a media source's items
written out as JSON (title, link, published, duration, views, tags, watched…).
What goes out is one series of bars — a label and a number each — which is
the one shape every chart on a pamphlet is drawn from.

Between the two, the box says:

* **Rows** — where the list is (`data.children`); blank finds it.
* **Label** — the path in each row that names its bar. A date can be grouped
  by day, week, month, weekday or hour; a list (tags) gives a bar per entry.
* **Value** — the path to a number, or nothing to count rows.
* **Combine** — what rows sharing a label become: sum, count, average, min,
  max or the latest seen.
* **Sort** and **Limit** — which bars, in what order.

Paths are the REST source's own: dots between steps, numbers for a place in
a list.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Channel, GraphNode, Video
from ...sources import rest
from .errors import GraphError

GROUPS: tuple[tuple[str, str], ...] = (
    ("none", "As it is"),
    ("day", "By day"),
    ("week", "By week"),
    ("month", "By month"),
    ("weekday", "By weekday"),
    ("hour", "By hour of day"),
)
COMBINES: tuple[tuple[str, str], ...] = (
    ("count", "Count rows"),
    ("sum", "Add up"),
    ("average", "Average"),
    ("min", "Smallest"),
    ("max", "Largest"),
    ("latest", "Last one seen"),
)
SORTS: tuple[tuple[str, str], ...] = (
    ("value-desc", "Biggest first"),
    ("value-asc", "Smallest first"),
    ("label-asc", "By label, A to Z (dates oldest first)"),
    ("label-desc", "By label, Z to A (dates newest first)"),
    ("as-is", "As they come"),
)
DRAWS: tuple[tuple[str, str], ...] = (
    ("auto", "Columns for dates, rows otherwise"),
    ("across", "Columns"),
    ("rows", "Rows"),
)

DEFAULTS: dict[str, Any] = {
    "rows": "", "label": "", "group": "none", "value": "",
    "combine": "count", "sort": "value-desc", "limit": 12, "draw": "auto",
}

#: The most bars a Format box gives a chart, and the most rows it reads.
MOST_BARS = 60
MOST_ROWS = 5000

#: How many of a media source's items are written out as JSON for one.
MEDIA_ITEMS = 1000

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def settings(node: GraphNode) -> dict[str, Any]:
    said = dict(DEFAULTS)
    try:
        stored = json.loads(node.format_spec or "{}")
    except ValueError:
        stored = {}
    if isinstance(stored, dict):
        said.update({key: value for key, value in stored.items() if key in said})
    return said


def save(node: GraphNode, form: Mapping[str, str]) -> None:
    """Set a Format box from its panel's `format_<setting>` fields."""
    said = settings(node)
    for name in ("rows", "label", "value"):
        value = form.get(f"format_{name}")
        if value is not None:
            said[name] = str(value).strip()[:200]
    for name, choices in (("group", GROUPS), ("combine", COMBINES), ("sort", SORTS), ("draw", DRAWS)):
        value = form.get(f"format_{name}")
        if value is None:
            continue
        if value not in dict(choices):
            raise GraphError(f"“{value}” is not something a Format box can do.")
        said[name] = value
    limit = form.get("format_limit")
    if limit is not None and str(limit).strip():
        if not str(limit).strip().isdigit():
            raise GraphError("How many bars has to be a whole number.")
        said["limit"] = max(1, min(MOST_BARS, int(str(limit).strip())))
    if said["combine"] not in ("count",) and not said["value"]:
        raise GraphError("Say which field holds the number to " + dict(COMBINES)[said["combine"]].lower() + ".")
    node.format_spec = json.dumps(said, sort_keys=True)


def words(node: GraphNode) -> str:
    """What a Format box does, said on the canvas."""
    said = settings(node)
    label = said["label"] or "each row"
    grouped = "" if said["group"] == "none" else f" {dict(GROUPS)[said['group']].lower()}"
    if said["combine"] == "count":
        return f"count of {label}{grouped}"
    combine = dict(COMBINES)[said["combine"]].lower()
    return f"{combine} {said['value']} by {label}{grouped}"


# -- what comes in -----------------------------------------------------------------


def media_rows(session: Session, channel: Channel) -> list[dict[str, Any]]:
    """A media source's items, newest first, as the JSON a Format box reads."""
    videos = session.scalars(
        select(Video)
        .where(Video.channel_pk == channel.id)
        .order_by(Video.published_at.desc(), Video.id.desc())
        .limit(MEDIA_ITEMS)
    )

    def stamp(value: dt.datetime | None) -> str | None:
        return value.isoformat() + "Z" if value is not None else None

    return [
        {
            "id": video.video_id,
            "title": video.title,
            "link": video.url,
            "kind": video.kind,
            "source": channel.title or channel.channel_id,
            "published": stamp(video.published_at),
            "arrived": stamp(video.discovered_at),
            "duration": video.duration_sec,
            "views": video.view_count,
            "likes": video.like_count,
            "tags": video.tag_list,
            "status": video.status,
            "watched": video.watched_at is not None,
            "watched_at": stamp(video.watched_at),
        }
        for video in videos
    ]


def data_for(session: Session, source: GraphNode) -> Any:
    """The JSON wired out of a source box: None if it has none yet."""
    channel = source.channel
    if channel is None:
        return None
    if channel.source_kind == "rest":
        if not channel.raw_snapshot:
            return None
        try:
            return json.loads(channel.raw_snapshot)
        except ValueError:
            return None
    return media_rows(session, channel)


# -- reshaping it ------------------------------------------------------------------


@dataclass(frozen=True)
class Bar:
    label: str
    #: Said in full on hover and in the table.
    long: str
    value: float

    @property
    def shown(self) -> str:
        """The value as a person writes it: no ".0" on a whole number."""
        return f"{self.value:,.0f}" if float(self.value).is_integer() else f"{self.value:,.2f}".rstrip("0")


@dataclass
class Shaped:
    bars: list[Bar] = field(default_factory=list)
    #: Columns across (dates read left to right) or rows down.
    across: bool = False
    #: Where the rows were found, and the fields the first of them has —
    #: for the panel to offer.
    rows_path: str = ""
    fields: list[str] = field(default_factory=list)
    rows: int = 0
    error: str = ""


def shape(data: Any, spec: Mapping[str, Any]) -> Shaped:
    """Reshape JSON into bars, as a Format box's settings say."""
    if data is None:
        return Shaped(error="Nothing has come in yet: it is read when its source is next checked.")
    try:
        rows, rows_path = rest.locate(data, str(spec.get("rows") or ""))
    except rest.RestError as exc:
        return Shaped(error=str(exc))
    rows = rows[:MOST_ROWS]
    shaped = Shaped(rows_path=rows_path, fields=_fields(rows), rows=len(rows))

    group = str(spec.get("group") or "none")
    combine = str(spec.get("combine") or "count")
    label_path = str(spec.get("label") or "")
    value_path = str(spec.get("value") or "")
    if not label_path:
        shaped.error = "Say which field labels each bar."
        return shaped

    gathered: dict[Any, list[float]] = {}
    names: dict[Any, tuple[str, str]] = {}
    for row in rows:
        named = rest.walk(row, label_path) if isinstance(row, (dict, list)) else None
        keys = named if isinstance(named, list) else [named]
        if combine == "count":
            number: float | None = 1.0
        else:
            number = _number(rest.walk(row, value_path) if isinstance(row, (dict, list)) else None)
        if number is None:
            continue
        for one in keys:
            key, short, long = _bucket(one, group)
            if key is None:
                continue
            gathered.setdefault(key, []).append(number)
            names[key] = (short, long)

    bars = [
        (key, Bar(label=names[key][0], long=names[key][1], value=_combine(numbers, combine)))
        for key, numbers in gathered.items()
    ]
    order = str(spec.get("sort") or "value-desc")
    if order == "value-desc":
        bars.sort(key=lambda pair: -pair[1].value)
    elif order == "value-asc":
        bars.sort(key=lambda pair: pair[1].value)
    elif order in ("label-asc", "label-desc"):
        bars.sort(key=lambda pair: _sortable(pair[0]), reverse=order == "label-desc")
    limit = int(spec.get("limit") or DEFAULTS["limit"])
    shaped.bars = [bar for _, bar in bars[: max(1, min(MOST_BARS, limit))]]

    draw = str(spec.get("draw") or "auto")
    shaped.across = draw == "across" or (draw == "auto" and group != "none")
    if not shaped.bars:
        shaped.error = "No row had both a label and a number at those paths."
    return shaped


def scale(bars: list[Bar]) -> float:
    """The top of the axis: the biggest bar rounded up to a readable number."""
    most = max((one.value for one in bars), default=0.0)
    if most <= 0:
        return 1.0
    if most <= 4:
        return float(math.ceil(most))
    step = 10 ** math.floor(math.log10(most))
    for nice in (1, 2, 2.5, 5, 10):
        if nice * step >= most:
            return float(nice * step)
    return most


def _fields(rows: list[Any]) -> list[str]:
    """The paths in the first rows, one level into anything nested."""
    found: list[str] = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if isinstance(value, dict):
                found.extend(f"{key}.{inner}" for inner in value if not isinstance(value[inner], (dict, list)))
            elif key not in found:
                found.append(key)
    return list(dict.fromkeys(found))[:60]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _combine(numbers: list[float], how: str) -> float:
    if how == "count":
        return float(len(numbers))
    if how == "average":
        return round(sum(numbers) / len(numbers), 2)
    if how == "min":
        return min(numbers)
    if how == "max":
        return max(numbers)
    if how == "latest":
        return numbers[-1]
    return round(sum(numbers), 2)


def _bucket(value: Any, group: str) -> tuple[Any, str, str]:
    """A label's key to gather by, its short name on the axis, and its long one."""
    if value is None or value == "":
        return None, "", ""
    if group == "none":
        if isinstance(value, (dict, list)):
            return None, "", ""
        said = str(value) if not isinstance(value, bool) else ("yes" if value else "no")
        return said, said[:24], said
    when = rest.when(value)
    if when is None:
        return None, "", ""
    if group == "day":
        day = when.date()
        return day, day.strftime("%-d"), day.strftime("%a %-d %b %Y")
    if group == "week":
        start = when.date() - dt.timedelta(days=when.weekday())
        return start, start.strftime("%-d %b"), "Week of " + start.strftime("%-d %b %Y")
    if group == "month":
        return (when.year, when.month), when.strftime("%b"), when.strftime("%B %Y")
    if group == "weekday":
        return when.weekday(), _WEEKDAYS[when.weekday()], when.strftime("%A")
    if group == "hour":
        return when.hour, f"{when.hour:02d}", f"{when.hour:02d}:00–{when.hour:02d}:59"
    return None, "", ""


def _sortable(key: Any) -> tuple[int, Any]:
    """Keys of one kind sort among themselves: dates as dates, words as words."""
    if isinstance(key, (int, float, tuple, dt.date)):
        return (0, key)
    return (1, str(key).lower())
