"""Charts for a Chart leaflet: data in, organised, drawn as the leaflet says.

A Chart leaflet is wired data — JSON from a source, from an operation box,
from a repository, a Transform or a Format box — and its own settings say
how to organise it:

* **Rows** — where the list is; blank finds it.
* **Label** — what each point is called, a path in each row; a date can be
  grouped by day, week, month, weekday or hour, and a list gives a point for
  each thing in it.
* **Value** — the number to show, a path, and how rows sharing a label are
  combined: counted, added up, averaged, the smallest, largest or last.
* **Series** — optionally, a path to split by: one line, or one bar of each
  group, per value found there. Five at most are named; the rest are Other.
* **Order** and **limit** — which points, in what order.

And how to draw it: columns, bars, a line, a stacked area, a pie, one number
or a table. Every chart is one scale: never two axes.

Everything here is worked out in Python — scales, line points, pie arcs —
so the template only has to set it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..sources import rest
from .graph import formatting

KINDS: tuple[tuple[str, str], ...] = (
    ("column", "Columns"),
    ("bar", "Bars"),
    ("line", "Line"),
    ("area", "Stacked area"),
    ("pie", "Pie"),
    ("number", "One number"),
    ("table", "Table"),
)

#: Series named before the rest are folded into Other: six colours in all,
#: the six validated on this app's surfaces, light and dark.
MOST_SERIES = 5
#: Slices a pie names before the rest are Other.
MOST_SLICES = 5
MOST_POINTS = 60

#: Line and area charts are drawn in a box this size, stretched to fit.
WIDTH, HEIGHT = 1000.0, 300.0

SPEC_DEFAULTS: dict[str, Any] = {
    "kind": "column", "rows": "", "label": "", "group": "none", "value": "",
    "combine": "count", "series": "", "sort": "label-asc", "limit": 30,
}


@dataclass(frozen=True)
class Category:
    short: str
    long: str


@dataclass
class Series:
    name: str
    values: list[float | None]
    #: Which of the six colours it wears, 1 to 6; Other is always 6.
    slot: int

    @property
    def total(self) -> float:
        return sum(value for value in self.values if value is not None)


@dataclass(frozen=True)
class Slice:
    name: str
    value: float
    share: float
    path: str
    slot: int


@dataclass
class Chart:
    kind: str = "column"
    categories: list[Category] = field(default_factory=list)
    series: list[Series] = field(default_factory=list)
    #: One number, for kind "number" — or what a Transform gave.
    figure: float | None = None
    error: str = ""
    #: What was found, for the dialog to offer.
    rows: int = 0
    rows_path: str = ""
    fields: list[str] = field(default_factory=list)
    #: What the value is, said in words, for a single series and the table.
    measure: str = ""
    #: A word said after a value on hover, like "waiting".
    unit: str = ""

    # -- scale -------------------------------------------------------------

    @property
    def stacked(self) -> bool:
        return self.kind == "area"

    @property
    def top(self) -> float:
        """The top of the one axis: the largest point, or largest stack,
        rounded up to a readable number."""
        if self.stacked:
            most = max((sum(s.values[i] or 0 for s in self.series)
                        for i in range(len(self.categories))), default=0.0)
        else:
            most = max((value or 0 for s in self.series for value in s.values), default=0.0)
        return nice_top(most)

    def share(self, value: float | None) -> float:
        """A value as a percentage of the top, for bar lengths."""
        return 0.0 if not value else round(100.0 * value / self.top, 2)

    # -- for the template --------------------------------------------------

    @property
    def single(self) -> bool:
        return len(self.series) == 1

    @property
    def every(self) -> int:
        """Label every nth category on an axis, so they do not collide."""
        return max(1, math.ceil(len(self.categories) / 8))

    def x(self, index: int) -> float:
        return (index + 0.5) * WIDTH / max(1, len(self.categories))

    def y(self, value: float) -> float:
        return round(HEIGHT - HEIGHT * value / self.top, 2)

    def line_segments(self, series: Series) -> list[str]:
        """A line's points, split where it has no value, as SVG point lists."""
        segments: list[list[str]] = [[]]
        for index, value in enumerate(series.values):
            if value is None:
                if segments[-1]:
                    segments.append([])
                continue
            segments[-1].append(f"{self.x(index):.1f},{self.y(value)}")
        return [" ".join(points) for points in segments if points]

    def alone(self, series: Series, index: int) -> bool:
        """A point with a gap either side: no line reaches it, so it is a dot."""
        values = series.values
        before = index > 0 and values[index - 1] is not None
        after = index + 1 < len(values) and values[index + 1] is not None
        return values[index] is not None and not before and not after

    def area_path(self, position: int) -> str:
        """A stacked band: the series' own top, back along the one below."""
        def level(upto: int, index: int) -> float:
            return sum(self.series[k].values[index] or 0 for k in range(upto + 1)) if upto >= 0 else 0.0

        count = len(self.categories)
        if count == 0:
            return ""
        upper = [f"{self.x(i):.1f},{self.y(level(position, i))}" for i in range(count)]
        lower = [f"{self.x(i):.1f},{self.y(level(position - 1, i))}" for i in reversed(range(count))]
        return "M" + " L".join(upper + lower) + " Z"

    def slices(self) -> list[Slice]:
        """A pie of the categories' totals: the largest five, and Other."""
        totals = [
            (category.long, sum(s.values[i] or 0 for s in self.series))
            for i, category in enumerate(self.categories)
        ]
        totals = sorted((pair for pair in totals if pair[1] > 0), key=lambda pair: -pair[1])
        named, rest_of = totals[:MOST_SLICES], totals[MOST_SLICES:]
        if rest_of:
            named.append(("Other", sum(value for _, value in rest_of)))
        whole = sum(value for _, value in named)
        found: list[Slice] = []
        turned = 0.0
        for index, (name, value) in enumerate(named):
            share = value / whole if whole else 0.0
            slot = 6 if name == "Other" and rest_of else min(index + 1, 6)
            found.append(Slice(name, value, round(share * 100, 1), _arc(turned, share), slot))
            turned += share
        return found

    @property
    def total(self) -> float:
        return sum(s.total for s in self.series)


def nice_top(most: float) -> float:
    """The largest value rounded up to 1, 2, 2.5 or 5 of its power of ten."""
    if most <= 0:
        return 1.0
    if most <= 4:
        return float(math.ceil(most))
    step = 10 ** math.floor(math.log10(most))
    for nice in (1, 2, 2.5, 5, 10):
        if nice * step >= most:
            return float(nice * step)
    return most


def shown(value: float | None) -> str:
    """A value as a person writes it: no ".0" on a whole number."""
    if value is None:
        return "—"
    if float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _arc(start: float, share: float) -> str:
    """A ring segment in a 100×100 box, from `start` round `share` of the way."""
    outer, inner, centre = 48.0, 30.0, 50.0
    if share >= 0.9999:
        # A whole ring: two halves, since one arc cannot end where it starts.
        return (f"M{centre},{centre - outer} A{outer},{outer} 0 1 1 {centre},{centre + outer} "
                f"A{outer},{outer} 0 1 1 {centre},{centre - outer} "
                f"M{centre},{centre - inner} A{inner},{inner} 0 1 0 {centre},{centre + inner} "
                f"A{inner},{inner} 0 1 0 {centre},{centre - inner} Z")

    def point(radius: float, turn: float) -> tuple[float, float]:
        angle = 2 * math.pi * turn - math.pi / 2
        return round(centre + radius * math.cos(angle), 3), round(centre + radius * math.sin(angle), 3)

    end = start + share
    large = 1 if share > 0.5 else 0
    (ax, ay), (bx, by) = point(outer, start), point(outer, end)
    (cx, cy), (dx, dy) = point(inner, end), point(inner, start)
    return (f"M{ax},{ay} A{outer},{outer} 0 {large} 1 {bx},{by} "
            f"L{cx},{cy} A{inner},{inner} 0 {large} 0 {dx},{dy} Z")


# -- building one -------------------------------------------------------------


def spec_of(said: Mapping[str, Any]) -> dict[str, Any]:
    """A leaflet's chart settings, every one filled in."""
    spec = dict(SPEC_DEFAULTS)
    spec.update({key: value for key, value in said.items() if key in SPEC_DEFAULTS and value is not None})
    return spec


def from_data(data: Any, said: Mapping[str, Any]) -> Chart:
    """Organise wired data into a chart, as a leaflet's settings say."""
    spec = spec_of(said)
    kind = str(spec["kind"])
    if data is None:
        return Chart(kind=kind, error="Nothing has come in yet: it is read when its source is next checked.")
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        return Chart(kind="number", figure=float(data))
    try:
        rows, rows_path = rest.locate(data, str(spec["rows"] or ""))
    except rest.RestError as exc:
        return Chart(kind=kind, error=str(exc))
    rows = rows[: formatting.MOST_ROWS]
    chart = Chart(kind=kind, rows=len(rows), rows_path=rows_path, fields=formatting._fields(rows))

    combine = str(spec["combine"])
    value_path, label_path = str(spec["value"] or ""), str(spec["label"] or "")
    series_path, group = str(spec["series"] or ""), str(spec["group"] or "none")
    chart.measure = "how many" if combine == "count" else f"{combine} of {value_path}"

    def number_of(row: Any) -> float | None:
        if combine == "count":
            return 1.0
        if not value_path:
            return None
        return formatting._number(rest.walk(row, value_path) if isinstance(row, (dict, list)) else None)

    if kind == "number" and not label_path:
        numbers = [n for n in (number_of(row) for row in rows) if n is not None]
        if not numbers:
            chart.error = "No row had a number at that path." if value_path else "Say which field holds the number."
            return chart
        chart.figure = formatting._combine(numbers, combine)
        return chart
    if not label_path:
        chart.error = "Say which field labels each point."
        return chart
    if combine != "count" and not value_path:
        chart.error = "Say which field holds the number."
        return chart

    cells: dict[tuple[Any, str], list[float]] = {}
    names: dict[Any, Category] = {}
    for row in rows:
        if not isinstance(row, (dict, list)):
            continue
        number = number_of(row)
        if number is None:
            continue
        named = rest.walk(row, label_path)
        keys = named if isinstance(named, list) else [named]
        series = _series_name(row, series_path) if series_path else chart.measure
        for one in keys:
            key, short, long = formatting._bucket(one, group)
            if key is None:
                continue
            cells.setdefault((key, series), []).append(number)
            names[key] = Category(short, long)
    if not cells:
        chart.error = "No row had both a label and a number at those paths."
        return chart

    # Series: the largest five named, the rest folded into Other.
    totals: dict[str, float] = {}
    for (_, series), numbers in cells.items():
        totals[series] = totals.get(series, 0.0) + sum(numbers)
    ranked = sorted(totals, key=lambda name: -totals[name])
    kept = ranked[:MOST_SERIES]
    folded = set(ranked[MOST_SERIES:])
    if folded:
        merged: dict[tuple[Any, str], list[float]] = {}
        for (key, series), numbers in cells.items():
            merged.setdefault((key, "Other" if series in folded else series), []).extend(numbers)
        cells = merged
        kept.append("Other")

    # Points: ordered and limited by what they add up to, or by their labels.
    keys = list(names)
    point_total = {key: sum(sum(cells.get((key, s), [])) for s in kept) for key in keys}
    order = str(spec["sort"])
    if order == "value-desc":
        keys.sort(key=lambda key: -point_total[key])
    elif order == "value-asc":
        keys.sort(key=lambda key: point_total[key])
    elif order in ("label-asc", "label-desc"):
        keys.sort(key=formatting._sortable, reverse=order == "label-desc")
    limit = max(1, min(MOST_POINTS, int(spec["limit"] or SPEC_DEFAULTS["limit"])))
    keys = keys[:limit]

    chart.categories = [names[key] for key in keys]
    chart.series = [
        Series(
            name=series,
            values=[
                formatting._combine(cells[(key, series)], combine) if (key, series) in cells
                # Nothing counted or added up there is none; an average of nothing is a gap.
                else 0.0 if combine in ("count", "sum") else None
                for key in keys
            ],
            slot=6 if series == "Other" else index + 1,
        )
        for index, series in enumerate(kept)
    ]
    return chart


def _series_name(row: Any, path: str) -> str:
    said = rest.walk(row, path)
    if said is None or said == "":
        return "(none)"
    if isinstance(said, bool):
        return "yes" if said else "no"
    if isinstance(said, list):
        return ", ".join(str(one) for one in said) or "(none)"
    return str(said)[:40]


def from_bars(bars: Sequence[Any], kind: str, measure: str = "", unit: str = "") -> Chart:
    """A chart from bars already worked out — a Format box's, or one of the
    built-in counts: one series."""
    if not bars:
        return Chart(kind=kind, error="Nothing to count yet.")
    return Chart(
        kind=kind,
        categories=[Category(bar.label, bar.long) for bar in bars],
        series=[Series(measure or "how many", [float(bar.value) for bar in bars], 1)],
        measure=measure,
        unit=unit,
    )


def words(said: Mapping[str, Any]) -> str:
    """What a chart shows, said on the canvas."""
    spec = spec_of(said)
    kind = dict(KINDS).get(str(spec["kind"]), "Chart").lower()
    if not spec["label"]:
        return f"{kind}: open it and organise the data" if spec["kind"] != "number" else "one number"
    what = "how many" if spec["combine"] == "count" else f"{spec['combine']} {spec['value']}"
    by = f" by {spec['label']}"
    split = f", per {spec['series']}" if spec["series"] else ""
    return f"{kind} of {what}{by}{split}"
