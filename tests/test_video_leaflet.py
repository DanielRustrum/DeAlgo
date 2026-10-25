"""A Video leaflet: one video on a pamphlet's page — the address it is
given, or the newest in a feed wired into it."""

from __future__ import annotations

import datetime as dt

import pytest

from pamphlets.models import Placement, Video, utcnow
from pamphlets.services import graph
from pamphlets.services.embeds import embed_for, youtube_id
from pamphlets.services.graph import leaflets
from tests.test_graph import canvas, node_for  # noqa: F401


@pytest.mark.parametrize("url, kind, src", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "youtube", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0"),
    ("https://youtu.be/dQw4w9WgXcQ", "youtube", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0"),
    ("https://youtube.com/shorts/dQw4w9WgXcQ", "youtube", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0"),
    ("https://vimeo.com/76979871", "vimeo", "https://player.vimeo.com/video/76979871"),
    ("https://example.org/clip.MP4", "file", "https://example.org/clip.MP4"),
    ("https://example.org/watch/42", "link", "https://example.org/watch/42"),
    ("", "", ""),
])
def test_an_address_is_played_the_way_its_host_allows(url, kind, src):
    found = embed_for(url)
    assert (found.kind, found.src) == (kind, src)


def test_not_every_youtube_looking_address_is_a_video():
    assert youtube_id("https://www.youtube.com/@somebody") == ""
    assert youtube_id("https://www.youtube.com/watch?v=short") == ""


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
    assert 'src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0"' in page and "Tonight" in page


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
