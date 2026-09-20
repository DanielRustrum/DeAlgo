"""Boxes a plugin puts in the palette.

A plugin node is a filter whose rule is somebody's Lua: given one item and
whatever its fields were set to, say whether it may carry on. A pure question
with a yes-or-no answer, which is the one shape that fits inside the sandbox.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from dealgo.models import Channel, GraphNode, Playlist, Video
from dealgo.plugins import registry
from dealgo.services import graph as graph_service
from tests.test_graph import boxes, canvas, only  # noqa: F401

SHIPPED = Path(__file__).resolve().parent.parent / "dealgo" / "plugins" / "builtin"

ONE_BOX = """return {
  api = 1, name = "%s",
  nodes = { { kind = "only", label = "Only", blurb = "One box.",
    keep = function() return true end } },
}"""

TWO_BOXES = """return {
  api = 1, name = "Pair",
  nodes = {
    { kind = "first", label = "First", keep = function() return true end },
    { kind = "second", label = "Second", keep = function() return true end },
  },
}"""

NO_BOXES = """return {
  api = 1, name = "Quiet",
  sources = { { kind = "quiet", recognise = function() return nil end } },
}"""


@pytest.fixture(autouse=True)
def a_known_registry():
    """Read the real folders before and after every test here.

    The registry is one object for the process, so a test that points it at a
    temporary folder leaves it there — and the next test would be reading a
    directory that has since been deleted. Rebuilding on the way out is not
    enough: the patch is still in place then.
    """
    registry.reload()
    yield
    registry.reload()


@pytest.fixture
def here(tmp_path, monkeypatch):
    folder = tmp_path / "plugins"
    folder.mkdir()
    monkeypatch.setattr(registry, "folder", lambda: folder)
    registry.reload()
    return folder


# -- declaring them --------------------------------------------------------


def test_a_node_needs_a_way_to_judge_something(here):
    (here / "lazy.lua").write_text(
        'return { api = 1, nodes = { { kind = "lazy", label = "Lazy" } } }', encoding="utf-8"
    )
    found = registry.read(here)

    assert "needs a `keep` function" in found.broken[0].trouble


def test_a_nodes_fields_are_checked_before_they_are_drawn(here):
    (here / "odd.lua").write_text("""
        return { api = 1, nodes = { { kind = "odd", keep = function() return true end,
          fields = { { label = "No name at all" } } } } }
    """, encoding="utf-8")
    found = registry.read(here)

    assert "a field needs a plain `name`" in found.broken[0].trouble


def test_a_plugin_may_offer_boxes_and_no_sources(here):
    """The shipped Shape plugin does exactly this."""
    (here / "quiet.lua").write_text(NO_BOXES, encoding="utf-8")
    (here / "pair.lua").write_text(TWO_BOXES, encoding="utf-8")
    found = registry.read(here)

    assert [n.ref for n in found.node_kinds()] == ["pair:first", "pair:second"]


# -- how the palette groups them -------------------------------------------


def test_a_plugin_with_one_box_shows_it_directly(canvas, here):
    """No dropdown of its own: a fold holding one row is a fold to open for
    no reason."""
    (here / "solo.lua").write_text(ONE_BOX % "Solo", encoding="utf-8")
    registry.reload()

    body = canvas.get("/channels").text
    inside = body.split("<summary>Plugins</summary>", 1)[1].split("</aside>", 1)[0]

    assert 'data-plugin-node="solo:only"' in inside
    # No fold of its own: a fold holding one row is a fold to open for no
    # reason. The row sits directly under the Plugins heading.
    assert "<summary>Solo</summary>" not in body


def test_a_plugin_with_several_boxes_gets_a_fold_of_its_own(canvas, here):
    (here / "pair.lua").write_text(TWO_BOXES, encoding="utf-8")
    registry.reload()

    body = canvas.get("/channels").text

    assert "<summary>Pair</summary>" in body
    assert 'data-plugin-node="pair:first"' in body
    assert 'data-plugin-node="pair:second"' in body
    # Folded inside the Plugins one, not beside it.
    inside = body.split("<summary>Plugins</summary>", 1)[1]
    assert inside.index("<summary>Pair</summary>") < inside.index("</aside>")


def test_a_plugin_with_no_boxes_is_not_mentioned(canvas, here):
    """An empty heading is a question about nothing."""
    (here / "quiet.lua").write_text(NO_BOXES, encoding="utf-8")
    registry.reload()

    body = canvas.get("/channels").text

    assert "<summary>Quiet</summary>" not in body


def test_with_no_plugin_offering_a_box_there_is_no_plugins_fold(canvas, here, monkeypatch):
    monkeypatch.setattr(registry, "shipped", lambda: here)   # nothing shipped either
    registry.reload()

    body = canvas.get("/channels").text

    assert "<summary>Plugins</summary>" not in body


def test_the_shipped_plugin_with_three_boxes_is_folded(canvas):
    body = canvas.get("/channels").text

    assert "<summary>Plugins</summary>" in body
    assert "<summary>Shape</summary>" in body
    assert 'data-plugin-node="shape:long-enough"' in body


# -- putting one on the canvas ---------------------------------------------


def test_a_plugin_box_can_be_dropped_and_is_named_after_itself(canvas, db):
    made = canvas.post(
        "/graph/nodes", data={"kind": "plugin", "plugin_node": "shape:not-shouting"}
    ).json()

    box = only(made, "plugin")
    assert box["title"] == "Not shouting"
    assert box["plugin"]["ref"] == "shape:not-shouting"
    assert box["note"] == "Holds titles that are mostly capitals."
    # Its fields arrive with the defaults its plugin declared.
    assert box["plugin"]["fields"][0]["value"] == "60"


def test_a_box_whose_plugin_is_not_loaded_is_refused(canvas):
    answer = canvas.post("/graph/nodes", data={"kind": "plugin", "plugin_node": "nope:nope"})

    assert answer.status_code == 400
    assert "not loaded" in answer.json()["error"]


def test_a_plugin_box_wires_where_a_filter_wires(canvas, db):
    drawn = canvas.get("/api/graph").json()
    source, feed = only(drawn, "source"), only(drawn, "feed")
    made = canvas.post(
        "/graph/nodes", data={"kind": "plugin", "plugin_node": "shape:has-words"}
    ).json()
    box = only(made, "plugin")

    into = canvas.post("/graph/connect", data={"source": source["id"], "target": box["id"]})
    onward = canvas.post("/graph/connect", data={"source": box["id"], "target": feed["id"]})

    assert into.status_code == 200 and onward.status_code == 200


def test_its_fields_are_saved_under_the_names_its_plugin_chose(canvas, db):
    made = canvas.post(
        "/graph/nodes", data={"kind": "plugin", "plugin_node": "shape:long-enough"}
    ).json()
    box = only(made, "plugin")

    answer = canvas.post(
        f"/graph/nodes/{box['id']}",
        data={"box_form": "1", "active": "1", "plugin_minutes": "12"},
    )

    assert answer.status_code == 200
    again = only(answer.json(), "plugin")
    assert again["plugin"]["fields"][0]["value"] == "12"
    with db.session_scope() as session:
        stored = session.get(GraphNode, box["id"])
    assert '"minutes": "12"' in stored.plugin_settings


def test_a_field_its_plugin_no_longer_declares_is_not_kept(canvas, db):
    """A box should not carry a dropped field for ever in a column nobody
    reads."""
    made = canvas.post(
        "/graph/nodes", data={"kind": "plugin", "plugin_node": "shape:long-enough"}
    ).json()
    box = only(made, "plugin")

    canvas.post(
        f"/graph/nodes/{box['id']}",
        data={"box_form": "1", "active": "1", "plugin_minutes": "9", "plugin_invented": "x"},
    )

    with db.session_scope() as session:
        stored = session.get(GraphNode, box["id"])
    assert "invented" not in (stored.plugin_settings or "")


# -- what it does in a run -------------------------------------------------


def wire_through_a_box(canvas, db, ref: str, settings: dict[str, str]):
    """Source → plugin box → feed, with the box set up."""
    drawn = canvas.get("/api/graph").json()
    source, feed = only(drawn, "source"), only(drawn, "feed")
    made = canvas.post("/graph/nodes", data={"kind": "plugin", "plugin_node": ref}).json()
    box = only(made, "plugin")
    canvas.post("/graph/connect", data={"source": source["id"], "target": box["id"]})
    canvas.post("/graph/connect", data={"source": box["id"], "target": feed["id"]})
    canvas.post(
        f"/graph/nodes/{box['id']}",
        data={"box_form": "1", "active": "1", **{f"plugin_{k}": v for k, v in settings.items()}},
    )
    return box["id"]


def test_a_plugin_box_holds_back_what_its_lua_refuses(canvas, db):
    from dealgo.services import sync as sync_service

    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
        session.add(Video(video_id="loud", channel_pk=channel.id,
                          title="WHY IS EVERYTHING SO LOUD TODAY", status="pending"))
        session.add(Video(video_id="calm", channel_pk=channel.id,
                          title="A perfectly ordinary title about things", status="pending"))

    wire_through_a_box(canvas, db, "shape:not-shouting", {"most": "60"})
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        loud = session.scalar(select(Video).where(Video.video_id == "loud"))
        calm = session.scalar(select(Video).where(Video.video_id == "calm"))
    assert loud.status == "skipped"
    assert "Not shouting" in loud.reason
    assert calm.status != "skipped"


def test_its_fields_change_what_it_holds(canvas, db):
    from dealgo.services import sync as sync_service

    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
        session.add(Video(video_id="loud", channel_pk=channel.id,
                          title="WHY IS EVERYTHING SO LOUD TODAY", status="pending"))

    # Anything up to all-capitals is fine, so nothing is held.
    wire_through_a_box(canvas, db, "shape:not-shouting", {"most": "100"})
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        loud = session.scalar(select(Video).where(Video.video_id == "loud"))
    assert loud.status != "skipped"


def test_a_box_whose_plugin_is_switched_off_narrows_nothing(canvas, db, here):
    """The box stays on the canvas and stops asking, which is what a filter
    with no rules does."""
    from dealgo.services import sync as sync_service

    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
        session.add(Video(video_id="loud", channel_pk=channel.id,
                          title="WHY IS EVERYTHING SO LOUD TODAY", status="pending"))

    wire_through_a_box(canvas, db, "shape:not-shouting", {"most": "10"})
    registry.set_paused("shape", paused=True)
    try:
        sync_service.run_sync("manual", force=True)
        with db.session_scope() as session:
            loud = session.scalar(select(Video).where(Video.video_id == "loud"))
        assert loud.status != "skipped"
    finally:
        registry.set_paused("shape", paused=False)


def test_a_box_that_throws_lets_the_item_by(canvas, db, here):
    """A filter nobody can read the mind of should not silently swallow a
    feed: the failure belongs in the log and the item belongs where it was
    going."""
    from dealgo.services import sync as sync_service

    (here / "cross.lua").write_text("""
        return { api = 1, name = "Cross", nodes = { { kind = "cross", label = "Cross",
          keep = function() error("I refuse to judge") end } } }
    """, encoding="utf-8")
    registry.reload()

    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
        session.add(Video(video_id="v0", channel_pk=channel.id, title="Anything", status="pending"))

    wire_through_a_box(canvas, db, "cross:cross", {})
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        kept = session.scalar(select(Video).where(Video.video_id == "v0"))
    assert kept.status != "skipped"


# -- the boxes the shipped plugins offer ------------------------------------


def an_item(**over):
    """One item as `_plugin_refusal` hands it over: plain values only."""
    base = {
        "title": "", "kind": "video", "words": "", "link": "", "duration": 0,
        "views": 0, "likes": 0, "is_short": False, "source": "youtube",
    }
    base.update(over)
    return base


def shipped():
    return registry.read(SHIPPED)


def test_every_source_plugin_offers_boxes_of_its_own():
    """Each grouping case is exercised by something real rather than only by
    a fixture: one box, several boxes, and none."""
    found = shipped()
    counted = {p.title: len(p.nodes) for p in found.plugins}

    assert counted["YouTube"] > 1 and counted["Reddit"] > 1   # folds of their own
    assert counted["Bluesky"] == 1 and counted["Substack"] == 1   # shown directly
    assert counted["Shape"] > 1


@pytest.mark.parametrize(
    "ref",
    [
        "youtube:no-shorts",
        "youtube:only-shorts",
        "youtube:watched-enough",
        "youtube:well-liked",
        "bluesky:said-something",
        "substack:long-read",
        "reddit:self-posts",
        "reddit:asks-a-question",
    ],
)
def test_a_source_plugins_box_lets_other_sources_by(ref):
    """The rule that keeps these safe to place anywhere. A box asking about
    view counts must not swallow a subreddit that has none, and "no likes
    recorded" is not "nobody liked it"."""
    found = shipped()
    plugin = ref.split(":")[0]
    elsewhere = "reddit" if plugin != "reddit" else "youtube"

    item = an_item(source=elsewhere, title="Anything at all", words="")

    assert found.keeps(ref, item, {}) is True


def test_shorts_can_be_held_or_demanded_on_one_path():
    """The channel's own switch does this everywhere; a box does it down one
    wire, which is the whole reason a path-specific one is worth having."""
    found = shipped()
    short, full = an_item(is_short=True), an_item(is_short=False)

    assert found.keeps("youtube:no-shorts", short, {}) is False
    assert found.keeps("youtube:no-shorts", full, {}) is True
    assert found.keeps("youtube:only-shorts", short, {}) is True
    assert found.keeps("youtube:only-shorts", full, {}) is False


def test_a_count_nobody_recorded_is_not_a_count_of_nothing():
    """Details are fetched after discovery and a channel may hide them, so a
    missing view count must not read as an unpopular video."""
    found = shipped()

    assert found.keeps("youtube:watched-enough", an_item(views=0), {"views": "1000"}) is True
    assert found.keeps("youtube:watched-enough", an_item(views=50), {"views": "1000"}) is False
    assert found.keeps("youtube:well-liked", an_item(likes=0), {"likes": "100"}) is True


def test_reddit_tells_a_written_post_from_a_link_share():
    found = shipped()
    wrote = an_item(source="reddit", words="x" * 200)
    shared = an_item(source="reddit", words="x")

    assert found.keeps("reddit:self-posts", wrote, {"least": "80"}) is True
    assert found.keeps("reddit:self-posts", shared, {"least": "80"}) is False


@pytest.mark.parametrize(
    "title, asking",
    [
        ("How do I bias this transistor", True),
        ("Is this resistor dead?", True),
        ("Anyone recognise this chip", True),
        ("help with my adder", True),
        ("Look at this scope I found", False),
        ("Finished my 4-bit CPU", False),
    ],
)
def test_reddit_spots_a_question_with_or_without_the_mark(title, asking):
    """Plenty of questions are asked without one, and the openers are the
    giveaway."""
    found = shipped()

    assert found.keeps("reddit:asks-a-question", an_item(source="reddit", title=title), {}) is asking


def test_bluesky_measures_what_was_said_not_what_was_linked():
    """A link share is long without saying anything."""
    found = shipped()
    bare = an_item(source="bluesky", title="https://example.com/a-very-long-address-indeed")
    said = an_item(source="bluesky", title="A real thought about a thing")

    assert found.keeps("bluesky:said-something", bare, {"least": "24"}) is False
    assert found.keeps("bluesky:said-something", said, {"least": "24"}) is True


def test_substack_holds_the_short_ones():
    found = shipped()

    assert found.keeps("substack:long-read", an_item(source="substack", words="x" * 2000), {}) is True
    assert found.keeps("substack:long-read", an_item(source="substack", words="a note"), {}) is False


def test_every_shipped_box_survives_an_item_with_nothing_in_it():
    """A box is placed before anything has been polled, and the first thing
    through may be missing everything it asks about."""
    found = shipped()
    empty = {"source": "youtube"}

    for node in found.node_kinds():
        assert found.keeps(node.ref, empty, {}) in (True, False), node.ref
