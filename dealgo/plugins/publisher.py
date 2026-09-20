"""Writing back to the service a feed came from, without knowing which it is.

De-Algo used to hold a YouTube client: four hundred lines that knew every
endpoint, every field name in every answer, and what each call costs against
the day's allowance. None of that was De-Algo's to know. It is YouTube's, and
it lives in the YouTube plugin now.

What is left here is the shape of the conversation. Something can be looked
up, a playlist can be read, added to and removed from; whichever service is
behind it answers in the same words. The plugin builds the request and reads
the answer; the host signs it, charges it, and turns what comes back into
these.

Only a plugin whose source kind is `playlistable` is asked. That is the same
rule that stops a Reddit post being pushed into a YouTube playlist, said from
the other end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..services.scope import OwnerId
from . import registry, site

log = logging.getLogger(__name__)


class PublishError(RuntimeError):
    """Something the service refused, said the way a person would want it."""

    def __init__(self, message: str, *, status: int | None = None, reason: str | None = None):
        super().__init__(message)
        self.status = status
        self.reason = reason

    @property
    def is_quota_error(self) -> bool:
        return self.reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded")

    @property
    def is_auth_error(self) -> bool:
        return self.status in (401, 403) and self.reason in (
            "authError", "unauthorized", "forbidden", None,
        )


@dataclass(frozen=True)
class ChannelInfo:
    channel_id: str
    title: str
    handle: str | None
    thumbnail_url: str | None
    #: Optional, because a source read from its feed alone carries no about
    #: text and should not pretend it knows there is none.
    description: str | None = None


@dataclass(frozen=True)
class VideoDetails:
    video_id: str
    title: str
    duration_sec: int | None
    live_state: str  # "none", "live", or "upcoming"
    privacy_status: str | None
    #: None where the service withholds them — a channel can hide its like
    #: count, and neither is given for something not published yet.
    view_count: int | None = None
    like_count: int | None = None


@dataclass(frozen=True)
class PlaylistInfo:
    playlist_id: str
    title: str
    item_count: int
    privacy_status: str | None


@dataclass(frozen=True)
class PlaylistItem:
    item_id: str
    video_id: str
    position: int
    title: str


#: What a call costs when its plugin does not say. One, because the cheap
#: calls are the common ones and guessing high would stop work that would
#: have been affordable.
DEFAULT_COST = 1


class Publisher:
    """The one plugin that can write back, asked in neutral words.

    Holds no credential. Everything that reaches the service goes through the
    plugin's own `account.send`, which is where the token is attached and the
    quota is charged.
    """

    def __init__(self, owner: OwnerId, *, writable: bool, readable: bool):
        self._owner = owner
        self._writable = writable
        self._readable = readable

    @property
    def has_write_access(self) -> bool:
        """Whether anything can be sent *to* the service. A key can read; only
        a signed-in account can write."""
        return self._writable and self._plugin() is not None

    @property
    def can_read(self) -> bool:
        return self._readable and self._plugin() is not None

    # -- looking things up -------------------------------------------------

    def resolve_channel(self, reference: str) -> ChannelInfo | None:
        rows = self._ask("resolve", reference)
        found = _first(rows)
        return _channel(found) if found else None

    def account_name(self) -> str | None:
        """What the connected account is called, for showing beside the
        sign-in. Nothing where the service will not say."""
        found = _first(self._ask("whoami"))
        return (_maybe(found, "title") if found else None)

    def get_channels(self, channel_ids: list[str]) -> dict[str, ChannelInfo]:
        if not channel_ids:
            return {}
        rows = self._ask("describe", list(channel_ids))
        found = [_channel(row) for row in _rows(rows)]
        return {one.channel_id: one for one in found if one.channel_id}

    def video_details(self, video_ids: list[str]) -> dict[str, VideoDetails]:
        if not video_ids:
            return {}
        rows = self._ask("details", list(video_ids))
        found = [_details(row) for row in _rows(rows)]
        return {one.video_id: one for one in found if one.video_id}

    # -- playlists ---------------------------------------------------------

    def my_playlists(self) -> list[PlaylistInfo]:
        return [_playlist(row) for row in _rows(self._ask("playlists"))]

    def get_playlist(self, playlist_id: str) -> PlaylistInfo | None:
        found = _first(self._ask("playlist", playlist_id))
        return _playlist(found) if found else None

    def create_playlist(
        self, title: str, *, description: str = "", privacy: str = "private"
    ) -> PlaylistInfo:
        found = _first(self._ask("create", title, description, privacy))
        if not found:
            raise PublishError("the playlist could not be created")
        return _playlist(found)

    def rename_playlist(self, playlist_id: str, title: str) -> None:
        if not self._ask("rename", playlist_id, title):
            raise PublishError("the playlist could not be renamed")

    def playlist_items(self, playlist_id: str) -> list[PlaylistItem]:
        return [_item(row) for row in _rows(self._ask("contents", playlist_id))]

    def insert_playlist_item(self, playlist_id: str, video_id: str) -> str:
        said = self._ask("add", playlist_id, video_id)
        given = _first(said)
        item_id = str((given or {}).get("item_id") or "")
        if not item_id:
            raise PublishError(f"{video_id} could not be added")
        return item_id

    def delete_playlist_item(self, item_id: str) -> None:
        if not self._ask("remove", item_id):
            raise PublishError("the item could not be removed")

    # -- the plumbing ------------------------------------------------------

    def _plugin(self) -> Any:
        """The plugin that owns a kind things can be published to.

        One, because two plugins both claiming to own publishing would be a
        question with no answer — and the same rule that keeps a Reddit post
        out of a YouTube playlist keeps a second one from appearing.
        """
        found = registry.current()
        for kind in found.source_kinds():
            if not kind.playlistable:
                continue
            plugin = next((p for p in found.working if p.title == kind.plugin), None)
            if plugin is not None and plugin.publishes:
                return plugin
        return None

    def _ask(self, what: str, *args: object) -> object:
        """Call one of the plugin's publishing functions.

        Inside `acting_for`, so the `account` capability knows whose
        credential to send with — everything a plugin reaches is scoped that
        way and this is no exception.
        """
        plugin = self._plugin()
        if plugin is None or plugin.box is None:
            raise PublishError("nothing here knows how to talk to that service")
        fn = plugin.publishes.get(what)
        if fn is None:
            raise PublishError(f"{plugin.title} cannot {what}")

        with site.acting_for(self._owner):
            try:
                return plugin.box.call(
                    fn, *(plugin.box.given(arg) for arg in args)
                )
            except Exception as exc:
                raise PublishError(f"{plugin.title}: {exc}") from exc


def cost_of(what: str) -> int:
    """What the plugin says one of its calls costs.

    Asked rather than kept here, because a service's price list is its own
    and a second copy would be a second thing to keep in step.
    """
    found = registry.current()
    for kind in found.source_kinds():
        if not kind.playlistable:
            continue
        plugin = next((p for p in found.working if p.title == kind.plugin), None)
        if plugin is not None and plugin.costs:
            try:
                return max(1, int(plugin.costs.get(what, DEFAULT_COST)))
            except (TypeError, ValueError):
                return DEFAULT_COST
    return DEFAULT_COST


# -- reading what a plugin answered ----------------------------------------
#
# Every one of these takes whatever came and makes the best sense of it. A
# plugin answering with the wrong shape should give a thin answer, not an
# exception halfway through a sync.


def _rows(said: object) -> list[dict[str, Any]]:
    if isinstance(said, list):
        return [row for row in said if isinstance(row, dict)]
    if isinstance(said, dict):
        return [said]
    return []


def _first(said: object) -> dict[str, Any] | None:
    rows = _rows(said)
    return rows[0] if rows else None


def _text(row: dict[str, Any], name: str) -> str:
    value = row.get(name)
    return str(value) if isinstance(value, (str, int, float)) else ""


def _maybe(row: dict[str, Any], name: str) -> str | None:
    return _text(row, name) or None


def _number(row: dict[str, Any], name: str) -> int | None:
    value = row.get(name)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _channel(row: dict[str, Any]) -> ChannelInfo:
    return ChannelInfo(
        channel_id=_text(row, "id"),
        title=_text(row, "title"),
        handle=_maybe(row, "handle"),
        thumbnail_url=_maybe(row, "thumbnail"),
        description=row.get("description") if isinstance(row.get("description"), str) else None,
    )


def _details(row: dict[str, Any]) -> VideoDetails:
    return VideoDetails(
        video_id=_text(row, "id"),
        title=_text(row, "title"),
        duration_sec=_number(row, "duration"),
        live_state=_text(row, "live") or "none",
        privacy_status=_maybe(row, "privacy"),
        view_count=_number(row, "views"),
        like_count=_number(row, "likes"),
    )


def _playlist(row: dict[str, Any]) -> PlaylistInfo:
    return PlaylistInfo(
        playlist_id=_text(row, "id"),
        title=_text(row, "title"),
        item_count=_number(row, "count") or 0,
        privacy_status=_maybe(row, "privacy"),
    )


def _item(row: dict[str, Any]) -> PlaylistItem:
    return PlaylistItem(
        item_id=_text(row, "item_id"),
        video_id=_text(row, "video_id"),
        position=_number(row, "position") or 0,
        title=_text(row, "title"),
    )
