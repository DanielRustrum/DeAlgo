"""Every page and endpoint, one module per part of the app.

Each module has its own `router`; the app includes them all. Who may reach
which is not decided here — that is the middleware's, by path, in guard.py.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    activity,
    admin,
    admin_accounts,
    canvas,
    configuration,
    feed,
    feeds,
    focus,
    connections,
    home,
    plugin_settings,
    plugins,
    settings,
    shell,
    signing_in,
    sources,
    theming,
    videos,
)

#: Every router, for the app to include.
ROUTERS: tuple[APIRouter, ...] = (
    activity.router,
    admin.router,
    admin_accounts.router,
    canvas.router,
    configuration.router,
    feed.router,
    feeds.router,
    focus.router,
    connections.router,
    home.router,
    plugin_settings.router,
    plugins.router,
    settings.router,
    shell.router,
    signing_in.router,
    sources.router,
    theming.router,
    videos.router,
)
