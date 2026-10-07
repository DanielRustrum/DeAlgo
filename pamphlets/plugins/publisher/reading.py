"""Making sense of what a publishing plugin answered.

Every one of these takes whatever came and makes the best sense of it. A
plugin answering with the wrong shape should give a thin answer, not an
exception halfway through a sync.
"""

from __future__ import annotations

from typing import Any

from .answers import ChannelInfo, PlaylistInfo, PlaylistItem, VideoDetails


def rows_in(said: object) -> list[dict[str, Any]]:
    """The rows in an answer: a list of tables, or one table as a list of one."""
    if isinstance(said, list):
        return [row for row in said if isinstance(row, dict)]
    if isinstance(said, dict):
        return [said]
    return []


def first_row(said: object) -> dict[str, Any] | None:
    """The first row of an answer, or None if it had none."""
    found = rows_in(said)
    return found[0] if found else None


def _text(row: dict[str, Any], name: str) -> str:
    """A field as text, or `""` when it is missing or not a plain value."""
    value = row.get(name)
    return str(value) if isinstance(value, (str, int, float)) else ""


def text_or_none(row: dict[str, Any], name: str) -> str | None:
    """A field as text, or None when it is missing or empty."""
    return _text(row, name) or None


def _number(row: dict[str, Any], name: str) -> int | None:
    """A field as a whole number, or None when it does not read as one."""
    value = row.get(name)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def channel_from(row: dict[str, Any]) -> ChannelInfo:
    """A `ChannelInfo` from one row of a plugin's answer."""
    return ChannelInfo(
        channel_id=_text(row, "id"),
        title=_text(row, "title"),
        handle=text_or_none(row, "handle"),
        thumbnail_url=text_or_none(row, "thumbnail"),
        description=row.get("description") if isinstance(row.get("description"), str) else None,
    )


def details_from(row: dict[str, Any]) -> VideoDetails:
    """A `VideoDetails` from one row of a plugin's answer."""
    return VideoDetails(
        video_id=_text(row, "id"),
        title=_text(row, "title"),
        duration_sec=_number(row, "duration"),
        live_state=_text(row, "live") or "none",
        privacy_status=text_or_none(row, "privacy"),
        view_count=_number(row, "views"),
        like_count=_number(row, "likes"),
    )


def playlist_from(row: dict[str, Any]) -> PlaylistInfo:
    """A `PlaylistInfo` from one row of a plugin's answer."""
    return PlaylistInfo(
        playlist_id=_text(row, "id"),
        title=_text(row, "title"),
        item_count=_number(row, "count") or 0,
        privacy_status=text_or_none(row, "privacy"),
    )


def item_from(row: dict[str, Any]) -> PlaylistItem:
    """A `PlaylistItem` from one row of a plugin's answer."""
    return PlaylistItem(
        item_id=_text(row, "item_id"),
        video_id=_text(row, "video_id"),
        position=_number(row, "position") or 0,
        title=_text(row, "title"),
    )
