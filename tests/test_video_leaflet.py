"""A Video leaflet: one video on a pamphlet's page — the address it is
given, or the newest in a feed wired into it. Pamphlets knows no video
service: an address plays in a frame only when an installed plugin's player
claims it."""

from __future__ import annotations

import datetime as dt
from urllib.parse import quote

import pytest

from pamphlets.config import CONFIG
from pamphlets.models import Placement, Video, utcnow
from pamphlets.services import graph
from pamphlets.services.embeds import embed_for
from pamphlets.services.graph import leaflets
from tests.test_graph import canvas, node_for  # noqa: F401

ORIGIN = quote(CONFIG.public_url.rstrip("/"), safe="")
FRAME = "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?enablejsapi=1&rel=0&autoplay=0&origin=" + ORIGIN


@pytest.mark.parametrize("url, kind, src", [
    # Claimed by the YouTube plugin the suite installs, and played in its player.
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "frame", FRAME),
    ("https://youtu.be/dQw4w9WgXcQ", "frame", FRAME),
    ("https://youtube.com/shorts/dQw4w9WgXcQ", "frame", FRAME),
    # No plugin claims it: Pamphlets has no Vimeo of its own.
    ("https://vimeo.com/76979871", "link", "https://vimeo.com/76979871"),
    ("https://example.org/clip.MP4", "file", "https://example.org/clip.MP4"),
    ("https://example.org/watch/42", "link", "https://example.org/watch/42"),
    ("javascript:alert(1)", "", ""),
    ("", "", ""),
])
def test_an_address_is_played_the_way_a_plugin_or_the_browser_can(db, url, kind, src):
    found = embed_for(url)
    assert (found.kind, found.src) == (kind, src)


def test_not_every_youtube_looking_address_is_a_video(db):
    assert embed_for("https://www.youtube.com/@somebody").kind == "link"
    assert embed_for("https://www.youtube.com/watch?v=short").kind == "link"


def test_with_its_plugin_off_an_address_is_only_a_link(db):
    from pamphlets.plugins import registry

    registry.set_paused("youtube", paused=True)
    try:
        assert embed_for("https://youtu.be/dQw4w9WgXcQ").kind == "link"
    finally:
        registry.set_paused("youtube", paused=False)


def _paper(session):
    paper = graph.add_pamphlet(session, label="Watch")
    video = graph.add_piece(session, kind="leaflet-video", host=paper)
    return paper, video


def test_it_takes_an_address_or_a_feed(canvas, db):
    with db.session_scope() as session:
        paper, video = _paper(session)
        with pytest.raises(graph.GraphError, match="http"):
            leaflets.save(video, {"leaflet_url": "javascript:alert(1)"}, set())
        leaflets.save(video, {"leaflet_url": "https://youtu.be/dQw4w9WgXcQ", "leaflet_heading": "Tonight"}, set())
        assert leaflets.words(video, {}) == "plays youtu.be"
        paper_pk = paper.id
    page = canvas.get(f"/pamphlets/{paper_pk}").text
    assert f'src="{FRAME}"'.replace("&", "&amp;") in page and "Tonight" in page
    # Sandboxed: another origin's page, which cannot navigate this one.
    assert 'sandbox="allow-scripts allow-same-origin allow-presentation' in page


def test_wired_to_a_feed_it_plays_the_newest_or_newest_unwatched(canvas, db):
    with db.session_scope() as session:
        feed = node_for(session, "feed", "One Feed")
        source = node_for(session, "source", "One Channel")
        paper, video = _paper(session)
        assert graph.connect(session, feed, video).carries == "page"
        older = Video(video_id="AAAAAAAAAAA", channel_pk=source.channel_pk, title="Older one",
                      published_at=utcnow() - dt.timedelta(days=1))
        newer = Video(video_id="BBBBBBBBBBB", channel_pk=source.channel_pk, title="Newer one",
                      published_at=utcnow(), watched_at=utcnow())
        session.add_all([older, newer])
        session.flush()
        for one in (older, newer):
            session.add(Placement(video_pk=one.id, playlist_pk=feed.playlist_pk, playlist_item_id=f"i{one.id}"))
        session.flush()
        assert leaflets.words(video, {feed.playlist_pk: "One Feed"}) == "plays the newest in “One Feed”"
        paper_pk, video_pk = paper.id, video.id
    page = canvas.get(f"/pamphlets/{paper_pk}").text
    assert "embed/BBBBBBBBBBB" in page and "Newer one" in page
    with db.session_scope() as session:
        from pamphlets.models import GraphNode

        leaflets.save(session.get(GraphNode, video_pk), {"leaflet_pick": "unwatched"}, set())
    page = canvas.get(f"/pamphlets/{paper_pk}").text
    assert "embed/AAAAAAAAAAA" in page and "Older one" in page
