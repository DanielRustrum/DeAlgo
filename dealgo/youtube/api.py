"""Thin YouTube Data API v3 client over httpx.

Only the handful of endpoints De-Algo actually needs, so the container does not
carry the full Google client stack.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterator
from urllib.parse import parse_qs, urlparse

import httpx

API_BASE = "https://www.googleapis.com/youtube/v3"

CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)

# Published quota costs, in units. The default daily budget is 10,000, so the
# expensive calls are the writes (50) and a channel search (100).
QUOTA_COSTS: dict[tuple[str, str], int] = {
    ("GET", "videos"): 1,
    ("GET", "channels"): 1,
    ("GET", "playlists"): 1,
    ("GET", "playlistItems"): 1,
    ("GET", "search"): 100,
    ("POST", "playlists"): 50,
    ("POST", "playlistItems"): 50,
    ("DELETE", "playlistItems"): 50,
}
QUOTA_COST_INSERT = QUOTA_COSTS[("POST", "playlistItems")]
QUOTA_COST_DELETE = QUOTA_COSTS[("DELETE", "playlistItems")]
QUOTA_COST_DEFAULT = 1


def cost_of(method: str, path: str) -> int:
    return QUOTA_COSTS.get((method.upper(), path), QUOTA_COST_DEFAULT)


class YouTubeAPIError(RuntimeError):
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
            "authError",
            "unauthorized",
            "forbidden",
            None,
        )


@dataclass(frozen=True)
class ChannelInfo:
    channel_id: str
    title: str
    handle: str | None
    thumbnail_url: str | None


@dataclass(frozen=True)
class VideoDetails:
    video_id: str
    title: str
    duration_sec: int | None
    live_state: str  # "none", "live", or "upcoming"
    privacy_status: str | None


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


def parse_duration(raw: str | None) -> int | None:
    """ISO-8601 duration (``PT4M13S``) to seconds."""
    if not raw:
        return None
    match = _DURATION_RE.match(raw)
    if not match:
        return None
    parts = {k: int(v) for k, v in match.groupdict(default="0").items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def parse_channel_reference(raw: str) -> tuple[str, str]:
    """Classify whatever the user pasted into ``(kind, value)``.

    ``kind`` is one of ``id``, ``handle``, ``username`` or ``search``.
    Accepts bare ids, @handles, and every shape of channel URL.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty channel reference")

    if CHANNEL_ID_RE.match(text):
        return "id", text
    if text.startswith("@"):
        return "handle", text

    if "://" not in text and text.startswith(("youtube.com", "www.youtube.com", "m.youtube.com")):
        text = "https://" + text

    if "://" in text:
        parsed = urlparse(text)
        query = parse_qs(parsed.query)
        segments = [s for s in parsed.path.split("/") if s]
        if segments:
            head = segments[0]
            if head == "channel" and len(segments) > 1:
                return "id", segments[1]
            if head == "user" and len(segments) > 1:
                return "username", segments[1]
            if head in {"c", "@"} and len(segments) > 1:
                return "search", segments[1]
            if head.startswith("@"):
                return "handle", head
            if head == "watch" and "v" in query:
                raise ValueError("that is a video link, not a channel link")
        raise ValueError(f"could not find a channel in {raw!r}")

    return "search", text


class YouTubeClient:
    """Calls are authorized by an OAuth access token, an API key, or both."""

    def __init__(
        self,
        *,
        http: httpx.Client,
        access_token: str | None = None,
        api_key: str | None = None,
        meter: Callable[[int], None] | None = None,
    ):
        self._http = http
        self._access_token = access_token
        self._api_key = api_key
        # Called with the quota cost of every request that reaches YouTube.
        self._meter = meter

    @property
    def has_write_access(self) -> bool:
        return bool(self._access_token)

    @property
    def can_read(self) -> bool:
        return bool(self._access_token or self._api_key)

    def _request(self, method: str, path: str, *, params: dict | None = None, json: Any = None) -> dict:
        params = dict(params or {})
        headers = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        elif self._api_key:
            params["key"] = self._api_key
        else:
            raise YouTubeAPIError("no YouTube credentials configured")

        response = self._http.request(method, f"{API_BASE}/{path}", params=params, json=json, headers=headers)

        payload: dict = {}
        if response.status_code != 204:
            try:
                payload = response.json()
            except ValueError:
                payload = {}

        reason = None
        if response.status_code >= 400:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            details = error.get("errors") or [{}]
            reason = details[0].get("reason")

        # Google charges for requests it refuses too, so the only call that
        # costs nothing is the one rejected for having no quota left.
        if self._meter is not None and reason != "quotaExceeded":
            self._meter(cost_of(method, path))

        if response.status_code >= 400:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            message = error.get("message") or f"HTTP {response.status_code}"
            raise YouTubeAPIError(
                f"{message} ({reason})" if reason else message,
                status=response.status_code,
                reason=reason,
            )
        return payload if response.status_code != 204 else {}

    def _paginate(self, path: str, params: dict, *, max_pages: int = 20) -> Iterator[dict]:
        page_token = None
        for _ in range(max_pages):
            page_params = dict(params)
            if page_token:
                page_params["pageToken"] = page_token
            payload = self._request("GET", path, params=page_params)
            yield from payload.get("items", [])
            page_token = payload.get("nextPageToken")
            if not page_token:
                return

    # -- channels -------------------------------------------------------

    def _channel_from_item(self, item: dict) -> ChannelInfo:
        snippet = item.get("snippet", {})
        thumbs = snippet.get("thumbnails", {})
        thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url")
        return ChannelInfo(
            channel_id=item.get("id", ""),
            title=snippet.get("title", ""),
            handle=snippet.get("customUrl"),
            thumbnail_url=thumb,
        )

    def get_channel(self, channel_id: str) -> ChannelInfo | None:
        payload = self._request("GET", "channels", params={"part": "snippet", "id": channel_id})
        items = payload.get("items") or []
        return self._channel_from_item(items[0]) if items else None

    def get_channels(self, channel_ids: list[str]) -> dict[str, ChannelInfo]:
        """Look up many channels at once — 50 ids still cost a single unit."""
        found: dict[str, ChannelInfo] = {}
        for start in range(0, len(channel_ids), 50):
            batch = channel_ids[start : start + 50]
            payload = self._request(
                "GET", "channels", params={"part": "snippet", "id": ",".join(batch)}
            )
            for item in payload.get("items", []):
                info = self._channel_from_item(item)
                if info.channel_id:
                    found[info.channel_id] = info
        return found

    def resolve_channel(self, reference: str) -> ChannelInfo | None:
        """Turn a user-supplied id/handle/URL/name into a channel."""
        kind, value = parse_channel_reference(reference)

        if kind == "id":
            return self.get_channel(value)

        params_by_kind = {
            "handle": {"forHandle": value},
            "username": {"forUsername": value},
        }
        if kind in params_by_kind:
            payload = self._request("GET", "channels", params={"part": "snippet", **params_by_kind[kind]})
            items = payload.get("items") or []
            if items:
                return self._channel_from_item(items[0])
            value = value.lstrip("@")

        # Last resort: a search costs 100 quota units, so it is never the first try.
        payload = self._request(
            "GET", "search", params={"part": "snippet", "type": "channel", "q": value, "maxResults": 1}
        )
        items = payload.get("items") or []
        if not items:
            return None
        found_id = items[0].get("snippet", {}).get("channelId") or items[0].get("id", {}).get("channelId")
        return self.get_channel(found_id) if found_id else None

    def my_channel_title(self) -> str | None:
        payload = self._request("GET", "channels", params={"part": "snippet", "mine": "true"})
        items = payload.get("items") or []
        return items[0].get("snippet", {}).get("title") if items else None

    # -- videos ---------------------------------------------------------

    def video_details(self, video_ids: list[str]) -> dict[str, VideoDetails]:
        """Durations and live state, batched 50 at a time (1 unit per batch)."""
        details: dict[str, VideoDetails] = {}
        for start in range(0, len(video_ids), 50):
            batch = video_ids[start : start + 50]
            payload = self._request(
                "GET",
                "videos",
                params={"part": "contentDetails,snippet,status", "id": ",".join(batch)},
            )
            for item in payload.get("items", []):
                snippet = item.get("snippet", {})
                details[item["id"]] = VideoDetails(
                    video_id=item["id"],
                    title=snippet.get("title", ""),
                    duration_sec=parse_duration(item.get("contentDetails", {}).get("duration")),
                    live_state=snippet.get("liveBroadcastContent", "none") or "none",
                    privacy_status=item.get("status", {}).get("privacyStatus"),
                )
        return details

    # -- playlists ------------------------------------------------------

    def my_playlists(self) -> list[PlaylistInfo]:
        items = self._paginate(
            "playlists", {"part": "snippet,contentDetails,status", "mine": "true", "maxResults": 50}
        )
        return [
            PlaylistInfo(
                playlist_id=item["id"],
                title=item.get("snippet", {}).get("title", ""),
                item_count=item.get("contentDetails", {}).get("itemCount", 0),
                privacy_status=item.get("status", {}).get("privacyStatus"),
            )
            for item in items
        ]

    def get_playlist(self, playlist_id: str) -> PlaylistInfo | None:
        payload = self._request(
            "GET", "playlists", params={"part": "snippet,contentDetails,status", "id": playlist_id}
        )
        items = payload.get("items") or []
        if not items:
            return None
        item = items[0]
        return PlaylistInfo(
            playlist_id=item["id"],
            title=item.get("snippet", {}).get("title", ""),
            item_count=item.get("contentDetails", {}).get("itemCount", 0),
            privacy_status=item.get("status", {}).get("privacyStatus"),
        )

    def create_playlist(self, title: str, *, description: str = "", privacy: str = "private") -> PlaylistInfo:
        payload = self._request(
            "POST",
            "playlists",
            params={"part": "snippet,status"},
            json={
                "snippet": {"title": title, "description": description},
                "status": {"privacyStatus": privacy},
            },
        )
        return PlaylistInfo(
            playlist_id=payload["id"],
            title=payload.get("snippet", {}).get("title", title),
            item_count=0,
            privacy_status=payload.get("status", {}).get("privacyStatus"),
        )

    def playlist_items(self, playlist_id: str) -> list[PlaylistItem]:
        items = self._paginate(
            "playlistItems", {"part": "snippet", "playlistId": playlist_id, "maxResults": 50}
        )
        result = []
        for item in items:
            snippet = item.get("snippet", {})
            resource = snippet.get("resourceId", {})
            if resource.get("kind") != "youtube#video":
                continue
            result.append(
                PlaylistItem(
                    item_id=item["id"],
                    video_id=resource.get("videoId", ""),
                    position=snippet.get("position", 0),
                    title=snippet.get("title", ""),
                )
            )
        return result

    def insert_playlist_item(self, playlist_id: str, video_id: str) -> str:
        payload = self._request(
            "POST",
            "playlistItems",
            params={"part": "snippet"},
            json={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        )
        return payload["id"]

    def delete_playlist_item(self, item_id: str) -> None:
        self._request("DELETE", "playlistItems", params={"id": item_id})
