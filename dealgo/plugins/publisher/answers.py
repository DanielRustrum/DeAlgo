"""What the publisher answers in, whichever service is behind it."""

from __future__ import annotations

from dataclasses import dataclass


class PublishError(RuntimeError):
    """Something the service refused, said the way a person would want it."""

    def __init__(self, message: str, *, status: int | None = None, reason: str | None = None):
        """An error, with the service's HTTP status and reason code when it gave them."""
        super().__init__(message)
        self.status = status
        self.reason = reason

    @property
    def is_quota_error(self) -> bool:
        """Whether the service refused because the day's quota is spent."""
        return self.reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded")

    @property
    def is_auth_error(self) -> bool:
        """Whether the service refused the sign-in itself."""
        return self.status in (401, 403) and self.reason in (
            "authError", "unauthorized", "forbidden", None,
        )


@dataclass(frozen=True)
class ChannelInfo:
    """A channel as the service describes it."""

    channel_id: str
    title: str
    handle: str | None
    thumbnail_url: str | None
    #: Optional, because a source read from its feed alone carries no about
    #: text and should not pretend it knows there is none.
    description: str | None = None


@dataclass(frozen=True)
class VideoDetails:
    """What the service says about one video beyond its feed entry."""

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
    """A playlist as the service describes it."""

    playlist_id: str
    title: str
    item_count: int
    privacy_status: str | None


@dataclass(frozen=True)
class PlaylistItem:
    """One item in a playlist: its own id, the video it holds, and its position."""

    item_id: str
    video_id: str
    position: int
    title: str
