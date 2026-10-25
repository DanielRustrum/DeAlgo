"""What is in a frozen canvas cannot be read: its pamphlets come up blank,
and its feeds are shown disabled and refused, until the canvas thaws."""

from __future__ import annotations

from pamphlets.services import graph
from pamphlets.services.graph import insides
from tests.test_canvases import in_canvas
from tests.test_graph import canvas, node_for  # noqa: F401


def _frozen_room(db):
    """A frozen canvas holding the one feed's box and a pamphlet showing it."""
    with db.session_scope() as session:
        feed = node_for(session, "feed", "One Feed")
        room = graph.add_canvas(session, label="Room")
        feed.inside_pk = room.id
        with in_canvas(room.id):
            paper = graph.add_pamphlet(session, label="Paper")
        session.flush()
        insides.freeze(session, room.id, True)
        return room.id, feed.playlist_pk, paper.id


def test_a_feed_whose_boxes_are_all_frozen_is_frozen(canvas, db):
    room, playlist, _ = _frozen_room(db)
    with db.session_scope() as session:
        assert insides.frozen_feeds(session) == {playlist: "Room"}
        # A second box for it, running somewhere, and it fills there.
        graph.add_feed(session, node_for(session, "feed", "One Feed").playlist, x=0, y=0)
        assert insides.frozen_feeds(session) == {}


def test_a_frozen_feed_is_disabled_on_the_shelf_and_refused(canvas, db):
    _, playlist, _ = _frozen_room(db)
    shelf = canvas.get("/feed").text
    assert "is-frozen" in shelf and "frozen with Room" in shelf
    assert f'href="/feed/{playlist}"' not in shelf
    opened = canvas.get(f"/feed/{playlist}", follow_redirects=False)
    assert opened.status_code in (302, 303) and opened.headers["location"].startswith("/feed")
    assert canvas.get(f"/partials/feed/{playlist}").status_code == 404
    assert "frozen" in canvas.get(f"/feeds/{playlist}").text


def test_a_frozen_pamphlet_is_blank_and_says_why(canvas, db):
    room, _, paper = _frozen_room(db)
    page = canvas.get(f"/pamphlets/{paper}").text
    assert "This pamphlet is frozen" in page and "Room" in page
    assert "stories inside" not in page
    assert "frozen with Room" in canvas.get("/pamphlets").text
    with db.session_scope() as session:
        insides.freeze(session, room, False)
    assert "This pamphlet is frozen" not in canvas.get(f"/pamphlets/{paper}").text

