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
from .plugin import PluginAppSetting, PluginState, PluginUserSetting
from .quota import AllowanceUsage
from .repository import RepositoryItem
from .run import RunEvent, SyncRun
from .settings import Settings
from .source import Channel
from .theme import UserImage, UserTheme
from .times import to_naive_utc, utcnow

__all__ = [
    "Base",
    "Channel",
    "channel_playlist",
    "CONDITION_LABELS",
    "GENERIC_ITEM_PREFIX",
    "GENERIC_PLAYLIST_PREFIX",
    "GraphEdge",
    "GraphNode",
    "LoginSession",
    "OAuthToken",
    "OFFLINE_ITEM_PREFIX",
    "Placement",
    "Playlist",
    "AllowanceUsage",
    "PluginAppSetting",
    "PluginState",
    "PluginUserSetting",
    "RepositoryItem",
    "RunEvent",
    "Settings",
    "SyncRun",
    "to_naive_utc",
    "User",
    "UserImage",
    "UserTheme",
    "utcnow",
    "Video",
]
