"""What the publisher answers in, whichever service is behind it."""

from __future__ import annotations

from dataclasses import dataclass


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
