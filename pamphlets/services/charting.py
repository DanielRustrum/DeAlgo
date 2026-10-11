"""Charts for the chart leaflets: data in, organised, handed to Chart.js.

Each chart is a leaflet of its own — Bar, Line, Pie, Radar, Polar area,
Scatter and Bubble, drawn in the browser by Chart.js (web/ts/charts.ts); a
Number leaflet and a Table leaflet show the same data undrawn. What comes in
down the data wire — JSON from a source, an operation, a repository, a
Transform or a Format box — is organised by the leaflet's settings:

* **Rows** — where the list is; blank finds it.
* **Label** — what each point is, a path in each row; a date can be grouped
  by day, week, month, weekday or hour, and a list gives a point for each
  thing in it. Left blank, the likeliest field is guessed, and said to be.
* **Value** — the number to show, and how rows sharing a label are combined:
  counted, added up, averaged, the smallest, largest or last.
* **Series** — optionally, a field to split by. Five are named; the rest
  are Other.
* **Order** and **limit** — which points, in what order.

A Scatter or Bubble chart places a point for each row instead, by its x and
y — and, for a bubble, its size.

Everything is worked out here; the browser only draws it, in the theme's
chart colours. Every chart has one scale: never two axes.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..sources import rest
from .graph import formatting
from .graph.templating import path_of

#: The kinds of chart, by the leaflet that draws each: its leaflet kind
#: without "leaflet-". Drawn ones go to Chart.js; number and table do not.
DRAWN = ("bar", "line", "pie", "radar", "polar", "scatter", "bubble")
KINDS = (*DRAWN, "number", "table")

#: Series named before the rest are folded into Other: six colours in all,
#: the theme's six chart colours.
MOST_SERIES = 5
#: Slices a pie (or polar area) names before the rest are Other.
MOST_SLICES = 5
MOST_POINTS = 60
#: Rows a Scatter or Bubble chart places, at most.
MOST_PLACED = 500

SPEC_DEFAULTS: dict[str, Any] = {
    "kind": "bar", "rows": "", "label": "", "group": "none", "value": "",
    "combine": "count", "series": "", "sort": "label-asc", "limit": 30,
    "x": "", "y": "", "size": "",
}

#: How a chart can be drawn, past what it shows (leaflets.STYLES' names).
STYLE_KEYS = ("direction", "stacking", "fill", "curve", "shape")


def kind_of(leaflet_kind: str) -> str:
    """The chart a leaflet draws: "leaflet-bar" draws a bar chart."""
    kind = leaflet_kind.removeprefix("leaflet-")
    return kind if kind in KINDS else "bar"


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


@dataclass
class Placed:
    """One series of a Scatter or Bubble chart: a point a row."""

    name: str
    slot: int
    points: list[dict[str, float]] = field(default_factory=list)


@dataclass(frozen=True)
class Slice:
    name: str
    value: float
    share: float
    slot: int


@dataclass
class Chart:
    kind: str = "bar"
    #: How it is drawn: direction, stacking, fill, curve, shape.
    style: dict[str, str] = field(default_factory=dict)
    categories: list[Category] = field(default_factory=list)
    series: list[Series] = field(default_factory=list)
    #: A Scatter or Bubble chart's points, by series.
    placed: list[Placed] = field(default_factory=list)
    #: One number, for a Number leaflet — or what a Transform gave.
    figure: float | None = None
    error: str = ""
    #: What was found, for the editor to offer.
    rows: int = 0
    rows_path: str = ""
    fields: list[str] = field(default_factory=list)
    #: What the value is, said in words, for a single series and the table.
    measure: str = ""
    #: A word said after a value on hover, like "waiting".
    unit: str = ""
    #: Fields that would make a good label, best first, for the editor to
    #: offer: {"path", "group", "label"}.
    suggested: list[dict[str, str]] = field(default_factory=list)
    #: When no label was chosen, the one used instead, said in words.
    guessed: str = ""
    #: A Scatter or Bubble chart's axes: what they are, and whether x is a date.
    x_name: str = ""
    y_name: str = ""
    x_dates: bool = False

    @property
    def single(self) -> bool:
        return len(self.series) == 1

    @property
    def total(self) -> float:
        return sum(s.total for s in self.series)

    @property
    def drawn(self) -> bool:
        """Whether Chart.js draws it, and there is something to draw."""
        if self.kind in ("scatter", "bubble"):
            return any(one.points for one in self.placed)
        return self.kind in DRAWN and bool(self.series) and self.total != 0

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
        return [
            Slice(name, value, round(100 * value / whole, 1) if whole else 0.0,
                  6 if name == "Other" and rest_of else min(index + 1, 6))
            for index, (name, value) in enumerate(named)
        ]

    def config(self) -> dict[str, Any]:
        """What the browser needs to draw it with Chart.js. Colours are left
        as slots: the browser reads the theme's chart colours for them."""
        said: dict[str, Any] = {
            "type": self.kind, "style": self.style, "measure": self.measure, "unit": self.unit,
        }
        if self.kind in ("pie", "polar"):
            slices = self.slices()
            said["labels"] = [one.name for one in slices]
            said["titles"] = said["labels"]
            said["series"] = [{"name": self.measure or "how many", "values": [one.value for one in slices],
                               "slots": [one.slot for one in slices]}]
            return said
        if self.kind in ("scatter", "bubble"):
            said["points"] = [{"name": one.name, "slot": one.slot, "data": one.points} for one in self.placed]
            said.update(xName=self.x_name, yName=self.y_name, xDates=self.x_dates)
            return said
        said["labels"] = [category.short for category in self.categories]
        said["titles"] = [category.long for category in self.categories]
        said["series"] = [{"name": s.name, "slot": s.slot, "values": s.values} for s in self.series]
        return said


def shown(value: float | None) -> str:
    """A value as a person writes it: no ".0" on a whole number."""
    if value is None:
        return "—"
    if float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


# -- building one -------------------------------------------------------------


def spec_of(said: Mapping[str, Any]) -> dict[str, Any]:
    """A leaflet's chart settings, every one filled in."""
    spec = dict(SPEC_DEFAULTS)
    spec.update({key: value for key, value in said.items() if key in SPEC_DEFAULTS and value is not None})
    # Fields are written {{ like.this }}; what is between the braces is the path.
    for key in ("rows", "label", "value", "series", "x", "y", "size"):
        spec[key] = path_of(spec[key])
    spec["kind"] = spec["kind"] if spec["kind"] in KINDS else "bar"
    return spec


def style_of(said: Mapping[str, Any]) -> dict[str, str]:
    """How a chart is drawn, from its settings: only the choices it has."""
    return {key: str(said[key]) for key in STYLE_KEYS if said.get(key)}


def from_data(data: Any, said: Mapping[str, Any]) -> Chart:
    """Organise wired data into a chart, as a leaflet's settings say."""
    spec = spec_of(said)
    kind = str(spec["kind"])
    if data is None:
        return Chart(kind=kind, error="Nothing has come in yet: it is read when its source is next checked.")
    figure = formatting.figure_of(data)
    if figure is not None:
        return Chart(kind="number", figure=figure[1], measure=figure[0])
    try:
        rows, rows_path = rest.locate(data, str(spec["rows"] or ""))
    except rest.RestError as exc:
        return Chart(kind=kind, error=str(exc))
    rows = rows[: formatting.MOST_ROWS]
    chart = Chart(kind=kind, style=style_of(said), rows=len(rows), rows_path=rows_path,
                  fields=formatting._fields(rows))
    if kind in ("scatter", "bubble"):
        return _placed(chart, rows, spec)

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

    if kind == "number":
        numbers = [n for n in (number_of(row) for row in rows) if n is not None]
        if not numbers:
            chart.error = "No row had a number at that path." if value_path else "Say which field holds the number."
            return chart
        chart.figure = formatting._combine(numbers, combine)
        return chart
    chart.suggested = suggest(rows)
    if not label_path and chart.suggested:
        # Nothing chosen yet: draw the likeliest chart rather than nothing,
        # and say it is a guess.
        best = chart.suggested[0]
        label_path, group = best["path"], best["group"]
        chart.guessed = best["label"]
    if not label_path:
        chart.error = "Say what each point is: drag a field into it."
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


#: Fields that name one thing each, which make a chart of one bar per row.
_UNIQUE = ("id", "link", "url", "title", "name", "description", "summary", "image", "thumbnail")


#: Fields that hold a date, even written as a number of seconds.
_DATES = ("published", "created", "created_utc", "date", "arrived", "updated", "watched_at", "time")


def _dated(value: Any) -> bool:
    """A date written as a date — 2026-10-09, or with its time — not a
    number that merely could be one."""
    return isinstance(value, str) and value[4:5] == "-" and value[:4].isdigit() and rest.when(value) is not None


def suggest(rows: list[Any]) -> list[dict[str, str]]:
    """Fields that would make a good label for a point, best first.

    Words that repeat — a source, a kind, a status — say what each point is;
    a date, grouped by day, gives a point a day; a yes or no splits in two;
    a list gives a point for each thing in it. A field that is different in
    every row, like a title, makes a point of every row and is left out.
    """
    sample = [row for row in rows[:200] if isinstance(row, (dict, list))]
    if not sample:
        return []
    found: list[tuple[int, dict[str, str]]] = []
    for path in formatting._fields(sample):
        values = [rest.walk(row, path) for row in sample]
        present = [value for value in values if value not in (None, "", [])]
        if not present:
            continue
        last = path.rsplit(".", 1)[-1].lower()
        if all(isinstance(value, bool) for value in present):
            found.append((3, {"path": path, "group": "none", "label": path}))
        elif all(isinstance(value, list) for value in present):
            found.append((4, {"path": path, "group": "none", "label": f"each of {path}"}))
        elif all(_dated(value) for value in present) \
                or (last in _DATES and all(rest.when(value) is not None for value in present)):
            found.append((2, {"path": path, "group": "day", "label": f"{path} by day"}))
        elif all(isinstance(value, str) for value in present) and last not in _UNIQUE:
            distinct = len({str(value) for value in present})
            if distinct == len(present) and len(present) > 3:
                continue
            # Words that repeat across a few values first; one value for all last.
            found.append((1 if 1 < distinct <= 20 else 5, {"path": path, "group": "none", "label": path}))
    found.sort(key=lambda pair: pair[0])
    return [pick for _, pick in found][:6]


def _series_name(row: Any, path: str) -> str:
    said = rest.walk(row, path)
    if said is None or said == "":
        return "(none)"
    if isinstance(said, bool):
        return "yes" if said else "no"
    if isinstance(said, list):
        return ", ".join(str(one) for one in said) or "(none)"
    return str(said)[:40]


def _placed(chart: Chart, rows: list[Any], spec: Mapping[str, Any]) -> Chart:
    """A Scatter or Bubble chart: a point for each row, at its x and y, sized
    by its size for a bubble, coloured by its series. A date along the
    bottom is placed by when it was."""
    x_path, y_path, size_path = str(spec["x"]), str(spec["y"]), str(spec["size"])
    series_path = str(spec["series"])
    if not x_path or not y_path:
        # Nothing chosen yet: the likeliest two, said to be a guess.
        dates, numbers = _measurable(rows)
        x_path = x_path or (dates[0] if dates else numbers[0] if numbers else "")
        y_path = y_path or next((one for one in numbers if one != x_path), "")
        if x_path and y_path:
            chart.guessed = f"{x_path} along, {y_path} up"
    if not x_path or not y_path:
        chart.error = "Say which field goes along the bottom and which goes up the side."
        return chart
    chart.x_name, chart.y_name = x_path, y_path

    found: list[tuple[str, float, float, float | None]] = []
    for row in rows[:MOST_PLACED]:
        if not isinstance(row, (dict, list)):
            continue
        across, up = rest.walk(row, x_path), formatting._number(rest.walk(row, y_path))
        x = formatting._number(across)
        if x is None and (when := rest.when(across)) is not None:
            x, chart.x_dates = when.timestamp() * 1000, True
        if x is None or up is None:
            continue
        size = formatting._number(rest.walk(row, size_path)) if size_path else None
        found.append((_series_name(row, series_path) if series_path else chart.y_name, x, up, size))
    if not found:
        chart.error = "No row had a number at both of those fields."
        return chart

    # Bubbles from 4 to 20 pixels across, by the square root, so area tells size.
    largest = max((abs(size) for *_, size in found if size is not None), default=0.0)
    counts: dict[str, int] = {}
    for name, *_ in found:
        counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts, key=lambda name: -counts[name])
    kept = ranked[:MOST_SERIES]
    by_name = {name: Placed(name, index + 1) for index, name in enumerate(kept)}
    if len(ranked) > MOST_SERIES:
        by_name["Other"] = Placed("Other", 6)
    for name, x, up, size in found:
        point = {"x": x, "y": up}
        if chart.kind == "bubble":
            point["r"] = 4 + 16 * math.sqrt(abs(size) / largest) if size is not None and largest else 6.0
        by_name[name if name in by_name else "Other"].points.append(point)
    chart.placed = list(by_name.values())
    return chart


def _measurable(rows: list[Any]) -> tuple[list[str], list[str]]:
    """The fields in the rows that hold dates, and those that hold numbers."""
    sample = [row for row in rows[:50] if isinstance(row, (dict, list))]
    dates: list[str] = []
    numbers: list[str] = []
    for path in formatting._fields(sample):
        present = [one for one in (rest.walk(row, path) for row in sample) if one not in (None, "")]
        if not present or any(isinstance(one, bool) for one in present):
            continue
        if all(isinstance(one, (int, float)) for one in present):
            numbers.append(path)
        elif all(_dated(one) for one in present):
            dates.append(path)
    return dates, numbers


def from_bars(bars: Sequence[Any], kind: str, measure: str = "", unit: str = "",
              style: Mapping[str, str] | None = None) -> Chart:
    """A chart from bars already worked out — a Format box's, or one of the
    built-in counts: one series."""
    if not bars:
        return Chart(kind=kind, error="Nothing to count yet.")
    return Chart(
        kind=kind,
        style=dict(style or {}),
        categories=[Category(bar.label, bar.long) for bar in bars],
        series=[Series(measure or "how many", [float(bar.value) for bar in bars], 1)],
        measure=measure,
        unit=unit,
    )


#: Each chart as the canvas names it.
NAMES = {"bar": "bar chart", "line": "line chart", "pie": "pie chart", "radar": "radar chart",
         "polar": "polar area chart", "scatter": "scatter chart", "bubble": "bubble chart",
         "number": "one number", "table": "table"}


def words(said: Mapping[str, Any]) -> str:
    """What a chart shows, said on the canvas."""
    spec = spec_of(said)
    kind = str(spec["kind"])
    if kind in ("scatter", "bubble"):
        if not (spec["x"] and spec["y"]):
            return "open it and say what goes along and up"
        return f"{spec['y']} against {spec['x']}" + (f", sized by {spec['size']}" if spec["size"] else "")
    what = "how many" if spec["combine"] == "count" else f"{spec['combine']} {spec['value']}"
    if kind == "number":
        return what if spec["combine"] != "count" else "how many rows there are"
    if not spec["label"]:
        return "open it and say what each one is"
    split = f", per {spec['series']}" if spec["series"] else ""
    return f"{what} by {spec['label']}{split}"
