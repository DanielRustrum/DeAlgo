"""Database schema, one table per module.

Everything De-Algo knows survives a restart: the channels being watched, every
video it has ever seen (so a video is never added twice), the OAuth grant, and
a log of sync runs.
"""

from __future__ import annotations

from .account import LoginSession, User
from .base import Base
from .canvas import CONDITION_LABELS, GraphEdge, GraphNode
from .feed import (
    GENERIC_ITEM_PREFIX,
    GENERIC_PLAYLIST_PREFIX,
    OFFLINE_ITEM_PREFIX,
    Playlist,
    channel_playlist,
)
from .item import Video
from .oauth import OAuthToken
from .placement import Placement
from .plugin import PluginState
from .quota import QuotaUsage
from .repository import RepositoryItem
from .run import RunEvent, SyncRun
from .settings import Settings
from .source import Channel
from .times import to_naive_utc, utcnow

__all__ = [
    "Base",
    "CONDITION_LABELS",
    "Channel",
    "GENERIC_ITEM_PREFIX",
    "GENERIC_PLAYLIST_PREFIX",
    "OFFLINE_ITEM_PREFIX",
    "GraphEdge",
    "GraphNode",
    "LoginSession",
    "OAuthToken",
    "Placement",
    "Playlist",
    "PluginState",
    "QuotaUsage",
    "RepositoryItem",
    "RunEvent",
    "Settings",
    "SyncRun",
    "User",
    "Video",
    "channel_playlist",
    "to_naive_utc",
    "utcnow",
]
