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

from ...models import Channel, GraphEdge, GraphNode, RepositoryItem, Video
from ...sources import rest
from .. import filters
from ..scope import OwnerId, owned
from .conditions import filter_rules
from .errors import GraphError
from .names import store_name, tag_name, tag_names
from .pieces import pieces_of, pieces_under
from .reading import nodes
from .stamps import stamped_life
from .templating import path_of

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
    label = path_of(said["label"]) or "each row"
    grouped = "" if said["group"] == "none" else f" {dict(GROUPS)[said['group']].lower()}"
    if said["combine"] == "count":
        return f"count of {label}{grouped}"
    combine = dict(COMBINES)[said["combine"]].lower()
    return f"{combine} {path_of(said['value'])} by {label}{grouped}"


# -- what comes in -----------------------------------------------------------------


def media_rows(session: Session, channel: Channel) -> list[dict[str, Any]]:
    """A media source's items, newest first, as the JSON a Format box reads."""
    videos = session.scalars(
        select(Video)
        .where(Video.channel_pk == channel.id)
        .order_by(Video.published_at.desc(), Video.id.desc())
        .limit(MEDIA_ITEMS)
    )
    return [_row(video) for video in videos]


def _row(video: Video) -> dict[str, Any]:
    """One item, as a row of JSON."""

    def stamp(value: dt.datetime | None) -> str | None:
        return value.isoformat() + "Z" if value is not None else None

    channel = video.channel
    return {
        "id": video.video_id,
        "title": video.title,
        "link": video.url,
        "kind": video.kind,
        "source": (channel.title or channel.channel_id) if channel is not None else "",
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


def repository_rows(session: Session, box: GraphNode, owner: OwnerId) -> list[dict[str, Any]]:
    """What is waiting in a Deposit or Withdraw box's repository, as rows."""
    named = store_name(box.repository)
    if not named:
        return []
    videos = session.scalars(
        owned(select(Video), Video, owner)
        .join(RepositoryItem, RepositoryItem.video_pk == Video.id)
        .where(RepositoryItem.name == named)
        .order_by(Video.published_at.desc(), Video.id.desc())
        .limit(MEDIA_ITEMS)
    )
    return [_row(video) for video in videos]


# -- through the operations --------------------------------------------------------


def data_into(session: Session, box: GraphNode, owner: OwnerId, depth: int = 0) -> Any:
    """The JSON wired into a box down its data wire, as it arrives: after
    whatever the boxes on the way did to it. None if nothing is wired in."""
    if depth > 40:
        return None  # a ring built before they were refused
    wire = session.scalar(
        owned(select(GraphEdge), GraphEdge, owner)
        .where(GraphEdge.target_pk == box.id, GraphEdge.carries == "data")
        .order_by(GraphEdge.id.desc())
    )
    start = session.get(GraphNode, wire.source_pk) if wire is not None else None
    if start is None:
        return None
    return data_out(session, start, owner, depth + 1)


def data_source(session: Session, box: GraphNode, owner: OwnerId, depth: int = 0) -> GraphNode | None:
    """The box at the start of the data wired into this one: a source or a
    repository. None where it starts as items, or nothing is wired in."""
    if depth > 40:
        return None
    wire = session.scalar(
        owned(select(GraphEdge), GraphEdge, owner)
        .where(GraphEdge.target_pk == box.id, GraphEdge.carries == "data")
        .order_by(GraphEdge.id.desc())
    )
    start = session.get(GraphNode, wire.source_pk) if wire is not None else None
    if start is None or start.kind in ("source", "deposit", "withdraw"):
        return start
    return data_source(session, start, owner, depth + 1)


def data_out(session: Session, box: GraphNode, owner: OwnerId, depth: int = 0) -> Any:
    """What a box gives out down a data wire."""
    if box.kind == "source":
        return data_for(session, box)
    if box.kind in ("deposit", "withdraw"):
        return repository_rows(session, box, owner)
    if not box.enabled:
        return None  # a box that is off passes nothing, data or items
    if box.kind == "transform":
        return transformed(session, box, owner, depth)
    if not _wired_in(session, box, owner, "data"):
        # Items in, data out: what the box lets through, read as rows — so a
        # media path can be charted or written about from any box along it.
        if not _wired_in(session, box, owner, "content"):
            return None
        return items_out(session, box, owner, depth)
    arriving = data_into(session, box, owner, depth)
    if arriving is None or box.kind == "decay":
        # A Decay is about time with an item, which rows do not have.
        return arriving
    return _through(rows_of(arriving), box, session, owner)


def _wired_in(session: Session, box: GraphNode, owner: OwnerId, carries: str) -> bool:
    """Whether anything is wired into a box that carries this."""
    return session.scalar(
        owned(select(GraphEdge.id), GraphEdge, owner)
        .where(GraphEdge.target_pk == box.id, GraphEdge.carries == carries)
    ) is not None


def _through(rows: list[Any], box: GraphNode, session: Session, owner: OwnerId) -> list[Any]:
    """Rows as an operation box leaves them, the way it leaves items."""
    if box.kind == "filter":
        return _filtered(rows, box, session, owner)
    if box.kind == "sort":
        return _sorted(rows, box, session, owner)
    if box.kind == "tag":
        named = tag_name(box.marks)
        return [_tagged(row, named) for row in rows] if named else rows
    if box.kind == "expire":
        return _unexpired(rows, box, session, owner)
    return rows


# -- items, read as rows -----------------------------------------------------------


def items_out(session: Session, box: GraphNode, owner: OwnerId, depth: int = 0) -> list[Any]:
    """The items a box sends on down its ▶ wires, as rows: a source's own,
    what a repository holds, or what an operation lets through of what
    reaches it. A REST source sends none — it gives data."""
    if depth > 40 or not box.enabled:
        return []
    if box.kind == "source":
        channel = box.channel
        if channel is None or channel.source_kind == "rest":
            return []
        return media_rows(session, channel)
    if box.kind in ("deposit", "withdraw"):
        return repository_rows(session, box, owner)
    if box.kind in ("filter", "sort", "tag", "decay", "expire"):
        return _through(items_into(session, box, owner, depth), box, session, owner)
    return []


def items_into(session: Session, box: GraphNode, owner: OwnerId, depth: int = 0) -> list[Any]:
    """Every item reaching a box down its ▶ wires, once each, as rows."""
    rows: list[Any] = []
    seen: set[Any] = set()
    for wire in session.scalars(
        owned(select(GraphEdge), GraphEdge, owner)
        .where(GraphEdge.target_pk == box.id, GraphEdge.carries == "content")
        .order_by(GraphEdge.id)
    ):
        start = session.get(GraphNode, wire.source_pk)
        if start is None:
            continue
        for row in items_out(session, start, owner, depth + 1):
            key = row.get("id") if isinstance(row, dict) else id(row)
            if key not in seen:
                seen.add(key)
                rows.append(row)
    return rows


# -- Transform boxes ---------------------------------------------------------------


def transformed(session: Session, box: GraphNode, owner: OwnerId, depth: int = 0) -> Any:
    """What a Transform box gives out: what comes in — data, or items read as
    rows — changed by each piece under it, nearest first. With none, it
    gives what came in as data."""
    has_data = session.scalar(
        owned(select(GraphEdge.id), GraphEdge, owner)
        .where(GraphEdge.target_pk == box.id, GraphEdge.carries == "data")
    ) is not None
    value: Any = data_into(session, box, owner, depth) if has_data else items_into(
        session, box, owner, depth
    )
    if value is None:
        return None
    for piece in pieces_under(nodes(session, owner), box.id):
        if not piece.enabled:
            continue
        if piece.kind == "count":
            # JSON, as everything down a data wire is: an object naming what
            # the number is, which a Chart leaflet shows as one figure.
            value = {"count": count_of(value)}
    return value


def count_of(value: Any) -> int:
    """How many: the rows in a list or found in an answer; one for anything
    that is a single thing."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        # An answer with rows in it counts its rows; one thing, like another
        # count, is one.
        return len(rows_of(value)) if figure_of(value) is None else 1
    return 0 if value is None else 1


def figure_of(data: Any) -> tuple[str, float] | None:
    """One number, and what it is called, if that is all the data is: a
    bare number, or an object with one field holding a number — what a
    Transform's Count gives, `{"count": 8}`. None for anything else."""
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        return "", float(data)
    if isinstance(data, dict) and len(data) == 1:
        name, value = next(iter(data.items()))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(name), float(value)
    return None


def rows_of(data: Any) -> list[Any]:
    """The rows in some JSON: itself if it is a list, else the list found in it."""
    if isinstance(data, list):
        return data
    try:
        return rest.locate(data, "")[0]
    except rest.RestError:
        return []


def _field(row: Any, name: str) -> Any:
    """A field of a row, where APIs usually put it, as a REST source finds it."""
    if not isinstance(row, dict):
        return None
    if name in row:
        return row[name]
    for place in [row] + [row[w] for w in rest.WRAPPERS if isinstance(row.get(w), dict)]:
        for candidate in rest.GUESSES.get(name, ()):
            if place.get(candidate) not in (None, ""):
                return place[candidate]
    return None


def _row_tags(row: Any) -> list[str]:
    said = _field(row, "tags")
    if isinstance(said, list):
        return [tag_name(str(one)) for one in said]
    if isinstance(said, str):
        return tag_names(said)
    return []


def _filtered(rows: list[Any], box: GraphNode, session: Session, owner: OwnerId) -> list[Any]:
    """The rows a Filter box's conditions let through, judged as items are."""
    rules = filter_rules(pieces_under(nodes(session, owner), box.id))
    wanted = tag_names(str(rules.get("tagged") or ""))
    unwanted = tag_names(str(rules.get("untagged") or ""))
    kept: list[Any] = []
    for row in rows:
        title = str(_field(row, "title") or "")
        if rules.get("title_include") and not filters.matches(str(rules["title_include"]), title):
            continue
        if rules.get("title_exclude") and filters.matches(str(rules["title_exclude"]), title):
            continue
        length = _number(_field(row, "duration"))
        if length is not None:
            if rules.get("min_duration_sec") and length < float(rules["min_duration_sec"]):
                continue
            if rules.get("max_duration_sec") and length > float(rules["max_duration_sec"]):
                continue
        tags = set(_row_tags(row))
        if wanted and tags.isdisjoint(wanted):
            continue
        if unwanted and not tags.isdisjoint(unwanted):
            continue
        kept.append(row)
    most = rules.get("max_per_run")
    return kept[: int(most)] if most else kept


_SORT_FIELDS = {"published": "published", "duration": "duration", "views": "views",
                "likes": "likes", "title": "title"}


def _sorted(rows: list[Any], box: GraphNode, session: Session, owner: OwnerId) -> list[Any]:
    """The rows in the order a Sort box's Order piece says."""
    order = next(
        (piece for piece in pieces_under(nodes(session, owner), box.id)
         if piece.kind == "order" and piece.enabled),
        None,
    )
    if order is None:
        return rows
    key = _SORT_FIELDS.get(order.sort_by or "published", "published")
    falling = (order.sort_dir or "desc") == "desc"

    def value(row: Any) -> tuple[int, Any]:
        said = _field(row, key)
        if key == "published":
            when = rest.when(said)
            return (0, when.timestamp()) if when is not None else (1, 0)
        if key == "title":
            return (0, str(said or "").lower())
        number = _number(said)
        return (0, number) if number is not None else (1, 0)

    present = [row for row in rows if value(row)[0] == 0]
    missing = [row for row in rows if value(row)[0] == 1]
    return sorted(present, key=lambda row: value(row)[1], reverse=falling) + missing


def _tagged(row: Any, named: str) -> Any:
    if not isinstance(row, dict):
        return row
    tags = _row_tags(row)
    return {**row, "tags": tags if named in tags else tags + [named]}


def _unexpired(rows: list[Any], box: GraphNode, session: Session, owner: OwnerId) -> list[Any]:
    """The rows younger than an Expire box's Timer, counted from when each was published."""
    minutes = stamped_life([box], pieces_of(session, owner))
    if minutes is None:
        return rows
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)
    kept = []
    for row in rows:
        when = rest.when(_field(row, "published"))
        if when is None or when >= since:
            kept.append(row)
    return kept


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
    figure = figure_of(data)
    if figure is not None:
        return Shaped(error=(
            f"That is one number ({figure[1]:g}), not rows to make bars from: wire it straight "
            "into a Chart leaflet to show it."
        ))
    try:
        rows, rows_path = rest.locate(data, path_of(spec.get("rows")))
    except rest.RestError as exc:
        return Shaped(error=str(exc))
    rows = rows[:MOST_ROWS]
    shaped = Shaped(rows_path=rows_path, fields=_fields(rows), rows=len(rows))

    group = str(spec.get("group") or "none")
    combine = str(spec.get("combine") or "count")
    label_path = path_of(spec.get("label"))
    value_path = path_of(spec.get("value"))
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
