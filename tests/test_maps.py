"""The Map leaflet: wired rows placed as dots, drawn by the Leaflet library.

Each row with a latitude and a longitude is a dot, in the theme's chart
colours by a field, sized by a number, saying what its row says when
pressed. The map pictures come from OpenStreetMap unless the admin names
another tile server.
"""

from __future__ import annotations

import json
import re

from pamphlets.models import GraphNode
from pamphlets.services import graph, mapping
from pamphlets.services.graph import leaflets
from tests.test_charts import drawn_node
from tests.test_format import a_rest_source, client  # noqa: F401 — the fixture

PLACES = {"places": [
    {"name": "Kew", "location": {"lat": 51.478, "lng": -0.295}, "kind": "garden", "visits": 400},
    {"name": "Wisley", "location": {"lat": 51.313, "lng": -0.475}, "kind": "garden", "visits": 100},
    {"name": "Eden", "location": {"lat": 50.361, "lng": -4.745}, "kind": "dome", "visits": 900},
    {"name": "Nowhere", "location": {"lat": None, "lng": 2}, "kind": "dome", "visits": 1},
    {"name": "Off the map", "location": {"lat": 120, "lng": 2}, "kind": "dome", "visits": 1},
]}


def configs(page):
    return [json.loads(found) for found in
            re.findall(r'<script type="application/json" data-map-config>(.*?)</script>', page, re.S)]


def test_rows_with_a_place_are_dots_and_the_fields_are_guessed():
    placed = mapping.from_data(PLACES, {})
    assert placed.guessed == "location.lat and location.lng"
    # The row with no latitude, and the one past the pole, are not placed.
    assert [(dot.lat, dot.lng) for dot in placed.dots] == [(51.478, -0.295), (51.313, -0.475), (50.361, -4.745)]


def test_dots_say_their_row_are_coloured_and_sized():
    placed = mapping.from_data(PLACES, {
        "lat": "{{ location.lat }}", "lng": "location.lng", "popup": "{{ name }}: {{ visits }} visits",
        "series": "{{ kind }}", "size": "visits",
    })
    assert not placed.guessed
    assert [dot.says for dot in placed.dots][0] == "Kew: 400 visits"
    assert placed.series == [("garden", 1), ("dome", 2)]
    assert [dot.slot for dot in placed.dots] == [1, 1, 2]
    assert placed.dots[2].radius == 20.0 and placed.dots[1].radius < placed.dots[0].radius


def test_it_says_what_is_missing():
    assert "latitude" in mapping.from_data([{"name": "x"}], {}).error
    assert "Nothing has come in" in mapping.from_data(None, {}).error
    assert "No row had" in mapping.from_data(PLACES, {"lat": "visits", "lng": "nowhere"}).error


def test_a_tile_address_must_be_one():
    assert mapping.tiles_problem("") == ""
    assert mapping.tiles_problem("https://tiles.example/{z}/{x}/{y}.png") == ""
    assert "https" in mapping.tiles_problem("http://tiles.example/{z}/{x}/{y}.png")
    assert "{y}" in mapping.tiles_problem("https://tiles.example/{z}/{x}.png")


def test_the_admin_names_the_tile_server(client, db):
    with db.session_scope() as session:
        assert mapping.tiles(session) == (mapping.DEFAULT_TILES, mapping.DEFAULT_CREDIT)
    assert "Maps" in client.get("/admin").text
    refused = client.post("/admin/maps", data={"tiles": "http://bad/{z}/{x}/{y}"}, follow_redirects=False)
    assert refused.status_code in (302, 303)
    client.post("/admin/maps", data={"tiles": "https://t.example/{z}/{x}/{y}.png", "credit": "© Example"})
    with db.session_scope() as session:
        assert mapping.tiles(session) == ("https://t.example/{z}/{x}/{y}.png", "© Example")
    client.post("/admin/maps", data={"tiles": "", "credit": ""})
    with db.session_scope() as session:
        assert mapping.tiles(session) == (mapping.DEFAULT_TILES, mapping.DEFAULT_CREDIT)


def a_map_from(session, source, **settings):
    pamphlet = graph.add_pamphlet(session, label="Places")
    node = graph.add_piece(session, kind="leaflet-map", host=pamphlet)
    leaflets.save(node, {f"leaflet_{k}": str(v) for k, v in settings.items()}, set())
    graph.connect(session, source, node)
    return pamphlet, node


def test_a_source_wires_into_a_map_on_a_pamphlet(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, PLACES)
        pamphlet, node = a_map_from(session, source, title="Gardens", popup="{{ name }}", series="kind")
        pamphlet_pk, map_pk = pamphlet.id, node.id
        assert [w["kind"] for w in graph.wires(session) if w["to"] == map_pk] == ["data"]

    page = client.get(f"/pamphlets/{pamphlet_pk}").text
    assert 'class="map-js" data-map' in page and "Gardens" in page
    [config] = configs(page)
    assert config["tiles"] == mapping.DEFAULT_TILES and config["credit"] == mapping.DEFAULT_CREDIT
    assert config["dots"][0] == {"lat": 51.478, "lng": -0.295, "slot": 1, "says": "Kew", "r": 6.0}
    # The key under the map, in the theme's colours by slot.
    assert 'data-slot="2"></span>dome' in page

    drawn = drawn_node(db, map_pk)
    # Guessed, not chosen: the canvas asks for them to be chosen.
    assert drawn["leaflet"]["wired"] and drawn["note"] == "open it and say where each row is"


def test_the_editor_places_dots_with_unsaved_settings(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, PLACES)
        _, node = a_map_from(session, source)
        map_pk = node.id
    seen = client.post(f"/graph/nodes/{map_pk}/inspect", data={"leaflet_popup": "{{ name }}"}).json()
    assert seen["input"]["count"] == 5
    assert "A guess" in seen["output"]["note"] and "data-map" in seen["output"]["html"]
    assert seen["output"]["rows"][0] == {"lat": 51.478, "lng": -0.295, "says": "Kew"}
    assert seen["filled"]["leaflet_popup"] == "Kew"


# -- focusing on a place ----------------------------------------------------------------

#: What Nominatim answers for "paris": its box is south, north, west, east.
PARIS = [
    {"display_name": "Paris, Île-de-France, France", "addresstype": "city",
     "boundingbox": ["48.8155755", "48.9021560", "2.2241220", "2.4697602"]},
    {"display_name": "Paris, Lamar County, Texas, United States", "addresstype": "town",
     "boundingbox": ["33.6118", "33.7217", "-95.6279", "-95.4567"]},
    {"display_name": "Nowhere useful", "boundingbox": "not a box"},
]


class FakeAnswer:
    def __init__(self, found):
        self.found = found

    def raise_for_status(self):
        return None

    def json(self):
        return self.found


class FakeClient:
    asked: list = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, address, params):
        FakeClient.asked.append((address, params["q"]))
        return FakeAnswer(PARIS)


def a_search_server(monkeypatch):
    from pamphlets import outgoing

    FakeClient.asked = []
    mapping._found.clear()
    monkeypatch.setattr(outgoing, "client", FakeClient)
    monkeypatch.setattr(mapping.time, "sleep", lambda _: None)


def test_a_place_is_found_by_name_with_its_edges_and_asked_once(monkeypatch):
    a_search_server(monkeypatch)
    places = mapping.find_places("  Paris ")
    assert [place.name for place in places] == ["Paris, Île-de-France, France",
                                                "Paris, Lamar County, Texas, United States"]
    # South, west, north, east.
    assert places[0].bounds == (48.8155755, 2.224122, 48.902156, 2.4697602)
    assert places[0].said()["bounds"] == "48.8156,2.22412,48.9022,2.46976"
    mapping.find_places("paris")
    assert FakeClient.asked == [(mapping.DEFAULT_SEARCH, "Paris")]
    assert mapping.find_places("   ") == []


def test_edges_must_be_an_area_on_the_globe():
    assert mapping.parse_bounds("48.8,2.2,48.9,2.5") == (48.8, 2.2, 48.9, 2.5)
    assert mapping.parse_bounds("48.9,2.2,48.8,2.5") is None   # north below south
    assert mapping.parse_bounds("95,0,96,1") is None
    assert mapping.parse_bounds("") is None


def test_a_map_focused_on_a_place_shows_it_with_or_without_data(client, db, monkeypatch):
    a_search_server(monkeypatch)
    with db.session_scope() as session:
        pamphlet = graph.add_pamphlet(session, label="Paris")
        node = graph.add_piece(session, kind="leaflet-map", host=pamphlet)
        pamphlet_pk, map_pk = pamphlet.id, node.id

    found = client.post(f"/graph/nodes/{map_pk}/map/find", data={"q": "paris"}).json()["places"]
    first = found[0]
    saved = client.post(f"/graph/nodes/{map_pk}", data={
        "label": "", "leaflet_focus": first["name"], "leaflet_bounds": first["bounds"],
    })
    assert saved.status_code == 200
    assert next(n for n in saved.json()["nodes"] if n["id"] == map_pk)["note"] == "a map of Paris"

    # Nothing wired in, and still a map: of the place.
    page = client.get(f"/pamphlets/{pamphlet_pk}").text
    [config] = configs(page)
    assert config["dots"] == [] and config["bounds"] == [[48.8156, 2.22412], [48.9022, 2.46976]]
    assert config["focus"] == "Paris, Île-de-France, France"

    refused = client.post(f"/graph/nodes/{map_pk}", data={"leaflet_bounds": "north of nowhere"})
    assert refused.status_code == 400
    client.post(f"/graph/nodes/{map_pk}", data={"leaflet_bounds": ""})
    with db.session_scope() as session:
        assert leaflets.settings(session.get(GraphNode, map_pk))["focus"] == ""


def test_the_admin_names_the_place_search_server(client, db, monkeypatch):
    a_search_server(monkeypatch)
    client.post("/admin/maps", data={"tiles": "", "credit": "", "search": "https://places.example/search"})
    with db.session_scope() as session:
        assert mapping.search_address(session) == "https://places.example/search"
        pamphlet = graph.add_pamphlet(session, label="P")
        map_pk = graph.add_piece(session, kind="leaflet-map", host=pamphlet).id
    client.post(f"/graph/nodes/{map_pk}/map/find", data={"q": "Lyon"})
    assert FakeClient.asked == [("https://places.example/search", "Lyon")]
    refused = client.post("/admin/maps", data={"search": "http://plain.example"}, follow_redirects=False)
    assert refused.status_code in (302, 303)
