"""Shared stand-ins for YouTube, used by the sync and watched test suites."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from dealgo.youtube import feeds
from dealgo.youtube.api import ChannelInfo, PlaylistItem, cost_of

CHANNEL_ID = "UCzzzzzzzzzzzzzzzzzzzzzz"
MAIN_PLAYLIST = "PL_target"


class FakeYouTube:
    """Stands in for YouTubeClient, recording what would have been written.

    Holds any number of playlists, since a channel may feed several.
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

    def _charge(self, method: str, path: str) -> None:
        if self._meter is not None:
            self._meter(cost_of(method, path))

    # -- the YouTubeClient surface sync and watched actually use ---------

    def video_details(self, video_ids):
        for _ in range(0, max(1, len(video_ids)), 50):
            self._charge("GET", "videos")
        return {vid: self.details[vid] for vid in video_ids if vid in self.details}

    def get_channels(self, channel_ids):
        self._charge("GET", "channels")
        return {
            channel_id: ChannelInfo(
                channel_id=channel_id,
                title="",
                handle=f"@{channel_id.lower()}",
                thumbnail_url=f"https://example.test/{channel_id}.jpg",
            )
            for channel_id in channel_ids
        }

    def playlist_items(self, playlist_id):
        self._charge("GET", "playlistItems")
        return list(self.playlists[playlist_id])

    def insert_playlist_item(self, playlist_id, video_id):
        self._charge("POST", "playlistItems")
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
        self._charge("DELETE", "playlistItems")
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


def entry(video_id: str, minutes_ago: int, title: str | None = None) -> feeds.FeedEntry:
    return feeds.FeedEntry(
        video_id=video_id,
        title=title or f"Video {video_id}",
        published_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago),
        thumbnail_url=None,
    )
