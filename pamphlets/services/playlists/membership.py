"""Which sources fill a feed, drawn as wires on the canvas."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ...models import Channel, Playlist
from .listing import PlaylistError


def follow_feed_links(session: Session, channel: Channel, before: int) -> None:
    """Pause a channel with nowhere to send videos; resume it when it gains a feed.

    Only the transitions are acted on — gaining the first feed, or losing the
    last. A channel paused by hand while it had feeds stays paused when another
    is added, because that pause was a decision rather than a missing setup.
    """
    after = len(channel.playlists)
    if before == 0 and after > 0:
        channel.enabled = True
    elif before > 0 and after == 0:
        channel.enabled = False
    session.flush()


def set_membership(session: Session, playlist: Playlist, channel_id: int, *, include: bool) -> str:
    """Add or remove one channel from one feed. Returns the channel's title.

    Drawn on the canvas, because that is where wires live now. Ticking wires
    the channel's first box to this feed; unticking takes out every wire from
    any of its boxes, since the answer here is about the channel and not
    about one box.

    "First" is by box id, which is the order they were put on the canvas. A
    channel with several boxes is a channel somebody has arranged deliberately
    — they can draw the wire they actually meant, and this at least never
    guesses differently twice.
    """
    from .. import graph as graph_service

    channel = session.get(Channel, channel_id)
    if channel is None:
        raise PlaylistError("That channel is no longer being watched.")

    before = len(channel.playlists)
    owner = channel.owner_pk
    # `load` rather than `nodes`: boxes are made the first time a canvas is
    # asked for, and a feed made a moment ago has not been drawn yet.
    drawn, _ = graph_service.load(session, owner)
    boxes = [
        node for node in drawn
        if node.kind == "source" and node.channel_pk == channel.id
    ]
    feed = next(
        (node for node in drawn if node.kind == "feed" and node.playlist_pk == playlist.id),
        None,
    )
    if feed is None:
        raise PlaylistError("That feed is not on the canvas.")
    if not boxes:
        boxes = [graph_service.add_source(session, owner, channel=channel)]

    if include:
        graph_service.connect(session, boxes[0], feed, owner)
    else:
        for box in boxes:
            for edge in graph_service.edges(session, owner):
                if edge.source_pk == box.id and edge.target_pk == feed.id:
                    graph_service.disconnect(session, edge.id, owner)

    session.refresh(channel)
    follow_feed_links(session, channel, before)
    return channel.title
