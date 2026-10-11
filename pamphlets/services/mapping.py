"""Maps for the Map leaflet: wired data placed on a map, drawn by Leaflet.

(Two things share a name here. A *leaflet* is a block of a pamphlet's page;
*Leaflet* is the map library, vendored into static/vendor, that draws this
one — web/ts/maps.ts.)

A Map leaflet is wired data — JSON from a source, an operation, a repository
or a Transform box — and each row with a latitude and a longitude is a dot
on the map. Its settings say where those are, what a dot says when it is
pressed (words, with `{{ fields }}` of its row), and, optionally, a field to
colour the dots by and a number to size them by. With nothing chosen, the
likeliest fields are guessed, and said to be.

The dots wear the theme's chart colours; the map under them is pictures
from a tile server — OpenStreetMap's unless the admin names another, under
Admin → Maps — muted towards the theme's surfaces in the browser.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from .. import outgoing
from ..models import SiteSetting
from ..sources import rest
from .graph import formatting
from .graph.templating import fill, path_of

#: Dots placed on one map, at most: past this a map is a smear.
MOST_DOTS = 1000
#: Colours named before the rest are Other: the theme's six chart colours.
MOST_SERIES = 5

#: Where map pictures come from unless the admin says otherwise.
DEFAULT_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
DEFAULT_CREDIT = "© OpenStreetMap contributors"
_TILES, _CREDIT = "map_tiles", "map_credit"

#: Where a place's name is looked up — OpenStreetMap's Nominatim, unless the
#: admin names another server that answers the same way.
DEFAULT_SEARCH = "https://nominatim.openstreetmap.org/search"
_SEARCH = "map_search"
#: Nominatim asks for one search a second at most, from any one app.
_SEARCH_GAP = 1.0

#: The fields a latitude and a longitude are usually called.
_LATITUDES = ("lat", "latitude")
_LONGITUDES = ("lng", "lon", "long", "longitude")

SPEC_DEFAULTS: dict[str, Any] = {
    "rows": "", "lat": "", "lng": "", "popup": "", "series": "", "size": "", "limit": 500,
    "focus": "", "bounds": "",
}


@dataclass
class Dot:
    lat: float
    lng: float
    #: Which of the six chart colours it wears, 1 to 6; Other is 6.
    slot: int
    #: What it says when pressed: plain words, set as text in the browser.
    says: str = ""
    #: Its radius in pixels: 6 unless sized by a number, then 4 to 20.
    radius: float = 6.0


@dataclass
class Map:
    dots: list[Dot] = field(default_factory=list)
    #: The colours in use, by name: [name, slot] in slot order.
    series: list[tuple[str, int]] = field(default_factory=list)
    error: str = ""
    guessed: str = ""
    rows: int = 0
    #: Where the map's pictures come from, and who to thank for them.
    tiles: str = DEFAULT_TILES
    credit: str = DEFAULT_CREDIT
    #: The area it is focused on, if one was chosen: its name, and its
    #: south, west, north and east edges.
    focus: str = ""
    bounds: tuple[float, float, float, float] | None = None
    #: Whether it stays where it is: no dragging, no zooming.
    fixed: bool = False

    @property
    def drawn(self) -> bool:
        """Whether there is a map to draw: dots, or an area to show."""
        return bool(self.dots) or self.bounds is not None

    def config(self) -> dict[str, Any]:
        """What the browser needs to draw it with Leaflet. Colours are left
        as slots: the browser reads the theme's chart colours for them."""
        return {
            "dots": [
                {"lat": dot.lat, "lng": dot.lng, "slot": dot.slot, "says": dot.says, "r": round(dot.radius, 1)}
                for dot in self.dots
            ],
            "series": [{"name": name, "slot": slot} for name, slot in self.series],
            "tiles": self.tiles,
            "credit": self.credit,
            "focus": self.focus,
            "fixed": self.fixed,
            "bounds": [[self.bounds[0], self.bounds[1]], [self.bounds[2], self.bounds[3]]] if self.bounds else None,
        }


# -- where the pictures come from ---------------------------------------------------


def tiles(session: Session) -> tuple[str, str]:
    """The tile address the admin chose, and its credit — or OpenStreetMap's."""
    address = session.get(SiteSetting, _TILES)
    credit = session.get(SiteSetting, _CREDIT)
    return (
        address.value if address is not None and address.value else DEFAULT_TILES,
        credit.value if credit is not None and address is not None and address.value else DEFAULT_CREDIT,
    )


def tiles_problem(address: str) -> str:
    """Why a tile address will not do, or "" if it will."""
    if not address:
        return ""
    parsed = urlparse(address)
    if parsed.scheme != "https" or not parsed.netloc:
        return "A tile address starts with https:// — a map page is never sent over plain http."
    missing = [part for part in ("{z}", "{x}", "{y}") if part not in address]
    if missing:
        return f"A tile address says where each picture is with {{z}}, {{x}} and {{y}}: it is missing {', '.join(missing)}."
    return ""


def set_tiles(session: Session, address: str, credit: str) -> None:
    """Point every map at another tile server — or, blank, back at OpenStreetMap."""
    for name, value in ((_TILES, address.strip()), (_CREDIT, credit.strip()[:300])):
        row = session.get(SiteSetting, name)
        if row is None:
            row = SiteSetting(name=name)
            session.add(row)
        row.value = value
    session.flush()


# -- finding a place ----------------------------------------------------------------


@dataclass(frozen=True)
class Place:
    """A place a name was found to be: what it is called in full, and its edges."""

    name: str
    kind: str
    bounds: tuple[float, float, float, float]

    def said(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "bounds": ",".join(f"{edge:g}" for edge in self.bounds)}


class SearchError(Exception):
    """A place could not be looked up: said in words."""


#: What has been looked up, by server and words: the same search twice is
#: not asked twice, and the one-a-second rule is kept across every account.
_found: dict[tuple[str, str], list[Place]] = {}
_last_search = [0.0]
_searching = threading.Lock()


def search_address(session: Session) -> str:
    """The place search server the admin chose, or Nominatim's."""
    row = session.get(SiteSetting, _SEARCH)
    return row.value if row is not None and row.value else DEFAULT_SEARCH


def set_search_address(session: Session, address: str) -> None:
    row = session.get(SiteSetting, _SEARCH)
    if row is None:
        row = SiteSetting(name=_SEARCH)
        session.add(row)
    row.value = address.strip()
    session.flush()


def search_problem(address: str) -> str:
    """Why a place search address will not do, or "" if it will."""
    if not address:
        return ""
    parsed = urlparse(address)
    if parsed.scheme != "https" or not parsed.netloc:
        return "A place search address starts with https://."
    return ""


def find_places(words: str, address: str = DEFAULT_SEARCH) -> list[Place]:
    """Look a place's name up — a city, a state, a country, an address —
    and say what it might be, likeliest first: five at most.

    Asked of the server here, only when somebody asks, and never more than
    once a second; a reader's browser never asks it anything."""
    asked = " ".join(words.split())[:200]
    if not asked:
        return []
    key = (address, asked.lower())
    if key in _found:
        return _found[key]
    with _searching:
        wait = _SEARCH_GAP - (time.monotonic() - _last_search[0])
        if wait > 0:
            time.sleep(wait)
        try:
            with outgoing.client() as http:
                answer = http.get(address, params={"q": asked, "format": "jsonv2", "limit": 5})
                answer.raise_for_status()
                found = answer.json()
        except Exception as exc:  # unreachable, refused, not JSON
            raise SearchError(f"Could not look it up: {exc}") from None
        finally:
            _last_search[0] = time.monotonic()
    places: list[Place] = []
    for one in found if isinstance(found, list) else []:
        edges = parse_bounds_nominatim(one.get("boundingbox")) if isinstance(one, dict) else None
        if edges is None:
            continue
        kind = str(one.get("addresstype") or one.get("type") or "")
        places.append(Place(str(one.get("display_name") or asked)[:300], kind, edges))
    _found[key] = places
    return places


def parse_bounds_nominatim(box: Any) -> tuple[float, float, float, float] | None:
    """Nominatim's box — south, north, west, east, as text — as south, west,
    north, east."""
    if not isinstance(box, list) or len(box) != 4:
        return None
    try:
        south, north, west, east = (float(one) for one in box)
    except (TypeError, ValueError):
        return None
    return parse_bounds(f"{south},{west},{north},{east}")


def parse_bounds(text: Any) -> tuple[float, float, float, float] | None:
    """An area's edges written "south,west,north,east" — or None if they
    are not four edges on the globe, the right way round."""
    try:
        south, west, north, east = (float(one) for one in str(text or "").split(","))
    except ValueError:
        return None
    if not (-90 <= south <= north <= 90 and -180 <= west <= 180 and -180 <= east <= 180):
        return None
    return south, west, north, east


# -- placing the dots ---------------------------------------------------------------


def spec_of(said: Mapping[str, Any]) -> dict[str, Any]:
    """A Map leaflet's settings, every one filled in; fields as paths."""
    spec = dict(SPEC_DEFAULTS)
    spec.update({key: value for key, value in said.items() if key in SPEC_DEFAULTS and value is not None})
    for key in ("rows", "lat", "lng", "series", "size"):
        spec[key] = path_of(spec[key])
    return spec


def _coordinate(value: Any, most: float) -> float | None:
    number = formatting._number(value)
    return number if number is not None and -most <= number <= most else None


def guess(rows: list[Any]) -> tuple[str, str]:
    """The fields that look like a latitude and a longitude: by their names
    first, as an API names them, and holding numbers that could be one."""
    sample = [row for row in rows[:50] if isinstance(row, (dict, list))]
    found: dict[str, str] = {}
    for path in formatting._fields(sample):
        name = path.rsplit(".", 1)[-1].lower()
        values = [one for one in (rest.walk(row, path) for row in sample) if one not in (None, "")]
        if not values:
            continue
        # Named like one, and mostly coordinates: a stray bad row does not rule it out.
        def mostly(most: float) -> bool:
            return sum(_coordinate(one, most) is not None for one in values) > 0.5 * len(values)

        if name in _LATITUDES and "lat" not in found and mostly(90):
            found["lat"] = path
        elif name in _LONGITUDES and "lng" not in found and mostly(180):
            found["lng"] = path
    return found.get("lat", ""), found.get("lng", "")


def from_data(data: Any, said: Mapping[str, Any]) -> Map:
    """Place wired data on a map, as a Map leaflet's settings say."""
    spec = spec_of(said)
    if data is None:
        return Map(error="Nothing has come in yet: it is read when its source is next checked.")
    try:
        rows, _ = rest.locate(data, str(spec["rows"] or ""))
    except rest.RestError as exc:
        return Map(error=str(exc))
    shown = Map(rows=len(rows))

    lat_path, lng_path = str(spec["lat"]), str(spec["lng"])
    if not lat_path or not lng_path:
        guessed_lat, guessed_lng = guess(rows)
        lat_path, lng_path = lat_path or guessed_lat, lng_path or guessed_lng
        if lat_path and lng_path:
            shown.guessed = f"{lat_path} and {lng_path}"
    if not lat_path or not lng_path:
        shown.error = "Say which field holds each row's latitude, and which its longitude."
        return shown

    limit = max(1, min(MOST_DOTS, int(spec["limit"] or SPEC_DEFAULTS["limit"])))
    series_path, size_path, popup = str(spec["series"]), str(spec["size"]), str(spec["popup"] or "")
    placed: list[tuple[float, float, str, str, float | None]] = []
    for row in rows:
        if len(placed) >= limit:
            break
        if not isinstance(row, (dict, list)):
            continue
        lat = _coordinate(rest.walk(row, lat_path), 90)
        lng = _coordinate(rest.walk(row, lng_path), 180)
        if lat is None or lng is None:
            continue
        named = rest.walk(row, series_path) if series_path else None
        size = formatting._number(rest.walk(row, size_path)) if size_path else None
        says = fill(popup, row) if popup else ""
        placed.append((lat, lng, "" if named in (None, "") else str(named)[:40], says[:500], size))
    if not placed:
        shown.error = "No row had a latitude and a longitude at those fields."
        return shown

    # Colours: the commonest five named, the rest Other.
    counts: dict[str, int] = {}
    for *_, named, _says, _size in placed:
        counts[named] = counts.get(named, 0) + 1
    ranked = sorted((name for name in counts if name), key=lambda name: -counts[name])
    slots = {name: index + 1 for index, name in enumerate(ranked[:MOST_SERIES])}
    if series_path:
        shown.series = [(name, slot) for name, slot in slots.items()]
        if len(ranked) > MOST_SERIES:
            shown.series.append(("Other", 6))
    largest = max((abs(size) for *_, size in placed if size is not None), default=0.0)
    for lat, lng, named, says, size in placed:
        radius = 4 + 16 * math.sqrt(abs(size) / largest) if size is not None and largest else 6.0
        shown.dots.append(Dot(lat, lng, slots.get(named, 6 if named else 1), says, radius))
    return shown


def focus_on(placed: Map, said: Mapping[str, Any]) -> Map:
    """Focus a map on the area its settings name, if they name one."""
    bounds = parse_bounds(said.get("bounds"))
    if bounds is not None:
        placed.bounds, placed.focus = bounds, str(said.get("focus") or "")
    placed.fixed = said.get("moves") == "fixed"
    return placed


def words(said: Mapping[str, Any]) -> str:
    """What a map shows, said on the canvas."""
    spec = spec_of(said)
    focus = str(said.get("focus") or "").split(",")[0]
    if not (spec["lat"] and spec["lng"]):
        return f"a map of {focus}" if focus and spec["bounds"] else "open it and say where each row is"
    by = f", coloured by {spec['series']}" if spec["series"] else ""
    over = f", over {focus}" if focus and spec["bounds"] else ""
    return f"a dot for each row at {spec['lat']}, {spec['lng']}{by}{over}"
