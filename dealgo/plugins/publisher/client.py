"""The one plugin that can write back, asked in neutral words."""

from __future__ import annotations

from typing import Any

from ...services.scope import OwnerId
from .. import registry
from ..capabilities import acting_for
from .answers import ChannelInfo, PlaylistInfo, PlaylistItem, PublishError, VideoDetails
from .reading import (
    channel_from,
    details_from,
    first_row,
    item_from,
    playlist_from,
    rows_in,
    text_or_none,
)

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
        """A publisher for one owner: `writable` with a sign-in, `readable` with a key."""
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
        """Whether anything can be read: a key or a sign-in, and a plugin to ask."""
        return self._readable and self._plugin() is not None

    # -- looking things up -------------------------------------------------

    def resolve_channel(self, reference: str) -> ChannelInfo | None:
        """The channel a reference such as an `@handle` names, or None."""
        rows = self._ask("resolve", reference)
        found = first_row(rows)
        return channel_from(found) if found else None

    def account_name(self) -> str | None:
        """What the connected account is called, for showing beside the
        sign-in. Nothing where the service will not say."""
        found = first_row(self._ask("whoami"))
        return (text_or_none(found, "title") if found else None)

    def get_channels(self, channel_ids: list[str]) -> dict[str, ChannelInfo]:
        """Details for each channel id the service knows, keyed by id."""
        if not channel_ids:
            return {}
        rows = self._ask("describe", list(channel_ids))
        found = [channel_from(row) for row in rows_in(rows)]
        return {one.channel_id: one for one in found if one.channel_id}

    def video_details(self, video_ids: list[str]) -> dict[str, VideoDetails]:
        """Duration, live state and counts for each video id, keyed by id."""
        if not video_ids:
            return {}
        rows = self._ask("details", list(video_ids))
        found = [details_from(row) for row in rows_in(rows)]
        return {one.video_id: one for one in found if one.video_id}

    # -- playlists ---------------------------------------------------------

    def my_playlists(self) -> list[PlaylistInfo]:
        """Every playlist the connected account owns."""
        return [playlist_from(row) for row in rows_in(self._ask("playlists"))]

    def get_playlist(self, playlist_id: str) -> PlaylistInfo | None:
        """One playlist by id, or None if it is not there."""
        found = first_row(self._ask("playlist", playlist_id))
        return playlist_from(found) if found else None

    def create_playlist(
        self, title: str, *, description: str = "", privacy: str = "private"
    ) -> PlaylistInfo:
        """Make a playlist. Raises `PublishError` if it could not be made."""
        found = first_row(self._ask("create", title, description, privacy))
        if not found:
            raise PublishError("the playlist could not be created")
        return playlist_from(found)

    def rename_playlist(self, playlist_id: str, title: str) -> None:
        """Rename a playlist. Raises `PublishError` if it could not be."""
        if not self._ask("rename", playlist_id, title):
            raise PublishError("the playlist could not be renamed")

    def playlist_items(self, playlist_id: str) -> list[PlaylistItem]:
        """Everything in a playlist, in its order."""
        return [item_from(row) for row in rows_in(self._ask("contents", playlist_id))]

    def insert_playlist_item(self, playlist_id: str, video_id: str) -> str:
        """Add a video to a playlist; returns the new item's id."""
        said = self._ask("add", playlist_id, video_id)
        given = first_row(said)
        item_id = str((given or {}).get("item_id") or "")
        if not item_id:
            raise PublishError(f"{video_id} could not be added")
        return item_id

    def delete_playlist_item(self, item_id: str) -> None:
        """Remove one item from a playlist. Raises `PublishError` on failure."""
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

        with acting_for(self._owner):
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
