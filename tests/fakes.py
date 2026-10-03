"""Shared stand-ins for a publisher, used by the sync and watched suites."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from dealgo.sources import syndication
from dealgo.plugins.publisher import ChannelInfo, PlaylistItem, cost_of

CHANNEL_ID = "UCzzzzzzzzzzzzzzzzzzzzzz"
MAIN_PLAYLIST = "PL_target"


class FakeYouTube:
    """Stands in for the Publisher, recording what would have been written.

    Holds any number of playlists, since a channel may feed several. Asked in
    the same neutral words the real one is, because what sits behind it is a
    plugin and no test here should be talking to YouTube.
    """

    def __init__(self, *, details=None, write=True, read=True):
        self.details = details or {}
        self.playlists: dict[str, list[PlaylistItem]] = defaultdict(list)
        self.has_write_access = write
        self.can_read = read
        self.inserted: list[tuple[str, str]] = []  # (playlist id, video id)
        self.deleted: list[str] = []
        self._counter = 0
        self._meter = None

    def bind_meter(self, meter):
        """Charge quota the way the real client does, so budgets bite in tests."""
        self._meter = meter
        return self

    def _charge(self, what: str) -> None:
        if self._meter is not None:
            self._meter(cost_of(what))

    # -- the Publisher surface sync and watched actually use -------------

    def video_details(self, video_ids):
        for _ in range(0, max(1, len(video_ids)), 50):
            self._charge("read")
        return {vid: self.details[vid] for vid in video_ids if vid in self.details}

    def get_channels(self, channel_ids):
        self._charge("read")
        return {
            channel_id: ChannelInfo(
                channel_id=channel_id,
                title="",
                handle=f"@{channel_id.lower()}",
                thumbnail_url=f"https://example.test/{channel_id}.jpg",
                description=f"All about {channel_id}.",
            )
            for channel_id in channel_ids
        }

    def playlist_items(self, playlist_id):
        self._charge("read")
        return list(self.playlists[playlist_id])

    def insert_playlist_item(self, playlist_id, video_id):
        self._charge("add")
        self._counter += 1
        item_id = f"item-{self._counter}"
        self.playlists[playlist_id].append(
            PlaylistItem(
                item_id=item_id,
                video_id=video_id,
                position=len(self.playlists[playlist_id]),
                title=video_id,
            )
        )
        self.inserted.append((playlist_id, video_id))
        return item_id

    def delete_playlist_item(self, item_id):
        self._charge("remove")
        self.deleted.append(item_id)
        for playlist_id, items in self.playlists.items():
            self.playlists[playlist_id] = [i for i in items if i.item_id != item_id]

    # -- conveniences for assertions -------------------------------------

    def contents(self, playlist_id=MAIN_PLAYLIST) -> list[str]:
        """Video ids currently in a playlist, in order."""
        return [item.video_id for item in self.playlists[playlist_id]]

    def item_id_for(self, video_id, playlist_id=MAIN_PLAYLIST) -> str | None:
        for item in self.playlists[playlist_id]:
            if item.video_id == video_id:
                return item.item_id
        return None

    def inserted_into(self, playlist_id=MAIN_PLAYLIST) -> list[str]:
        return [vid for pid, vid in self.inserted if pid == playlist_id]

    def seed(self, playlist_id, video_id, item_id="seeded-1"):
        """Put a video in a playlist as if someone had added it by hand."""
        self.playlists[playlist_id].append(
            PlaylistItem(item_id=item_id, video_id=video_id, position=0, title=video_id)
        )


def entry(
    video_id: str, minutes_ago: int, title: str | None = None, *, short: bool = False
) -> syndication.Item:
    """One upload, as YouTube's own feed writes it.

    A feed entry rather than a finished item: the host parses the feed and
    the YouTube plugin says what is YouTube's about it, so a fixture that
    handed over a finished item would be testing neither.
    """
    where = "shorts/" if short else "watch?v="
    return syndication.Item(
        guid=f"yt:video:{video_id}",
        title=title or f"Video {video_id}",
        link=f"https://www.youtube.com/{where}{video_id}",
        published_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago),
    )


def wire(session, channel, playlist):
    """Draw the wire that a source-to-feed link used to be.

    A source's wire belongs to the box it comes from, so pairing the channel
    with the feed is no longer enough to route anything. This does both: the
    pairing the rest of the app reads, and the wire the canvas routes from.
    """
    from dealgo.models import GraphEdge, GraphNode
    from sqlalchemy import select

    feed = session.scalar(
        select(GraphNode).where(
            GraphNode.kind == "feed", GraphNode.playlist_pk == playlist.id
        )
    )
    if feed is None:
        feed = GraphNode(
            owner_pk=playlist.owner_pk, kind="feed", playlist_pk=playlist.id,
            enabled=True, x=400, y=0,
        )
        session.add(feed)
        session.flush()

    boxes = list(
        session.scalars(
            select(GraphNode).where(
                GraphNode.kind == "source", GraphNode.channel_pk == channel.id
            )
        )
    )
    if not boxes:
        box = GraphNode(
            owner_pk=channel.owner_pk, kind="source", channel_pk=channel.id,
            enabled=True, x=0, y=0,
        )
        session.add(box)
        session.flush()
        boxes = [box]

    for box in boxes:
        already = session.scalar(
            select(GraphEdge).where(
                GraphEdge.source_pk == box.id, GraphEdge.target_pk == feed.id
            )
        )
        if already is None:
            session.add(GraphEdge(owner_pk=channel.owner_pk, source_pk=box.id, target_pk=feed.id))
    if playlist not in channel.playlists:
        channel.playlists.append(playlist)
    session.flush()


def unwire(session, channel):
    """Take out every wire from this channel's boxes to any feed."""
    from dealgo.models import GraphEdge, GraphNode
    from sqlalchemy import select

    boxes = [
        node.id
        for node in session.scalars(
            select(GraphNode).where(
                GraphNode.kind == "source", GraphNode.channel_pk == channel.id
            )
        )
    ]
    feeds = {
        node.id
        for node in session.scalars(select(GraphNode).where(GraphNode.kind == "feed"))
    }
    for edge in list(session.scalars(select(GraphEdge))):
        if edge.source_pk in boxes and edge.target_pk in feeds:
            session.delete(edge)
    channel.playlists = []
    session.flush()


def use_config(monkeypatch, config):
    """Run the app under another configuration, everywhere it reads one.

    Every module that imported CONFIG holds its own reference to it, so each
    loaded one is pointed at the new configuration — the web app is many
    modules, and patching a hand-picked few would leave the rest signed out.
    """
    import sys

    for name, module in list(sys.modules.items()):
        if (name == "dealgo" or name.startswith("dealgo.")) and hasattr(module, "CONFIG"):
            monkeypatch.setattr(module, "CONFIG", config)


def set_quota(*, daily: int | None = None, reserve: int | None = None, session=None) -> None:
    """Set the YouTube plugin's allowance, which are its settings for everyone now.

    Inside an open `session_scope`, pass its `session`: a second session
    writing while the first holds the database would wait on a lock. The
    value is then seen once that session commits.
    """
    from sqlalchemy import select

    from dealgo.models import PluginAppSetting
    from dealgo.services import plugin_settings

    values = {}
    if daily is not None:
        values["daily_quota"] = str(daily)
    if reserve is not None:
        values["quota_reserve"] = str(reserve)
    if session is None:
        plugin_settings.save("youtube", "app", None, values)
        return
    for name, value in values.items():
        key = plugin_settings.key_for("youtube", name)
        row = session.scalar(select(PluginAppSetting).where(PluginAppSetting.key == key))
        if row is None:
            session.add(PluginAppSetting(key=key, value=value))
        else:
            row.value = value
    session.flush()
    plugin_settings.drop_held()


def give_youtube_a_client() -> None:
    """The admin's half of signing in: an OAuth client on the YouTube plugin."""
    from dealgo.services import plugin_settings

    plugin_settings.save(
        "youtube", "app", None, {"client_id": "client-id", "client_secret": "secret"}
    )
