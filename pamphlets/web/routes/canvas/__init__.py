"""The canvas's API.

The server owns the graph: every change is a POST answered with the whole
graph again, and the browser redraws from that answer.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import editing, groups, inspecting, running, saving, trying

router = APIRouter()
for part in (editing, saving, groups, running, trying, inspecting):
    router.include_router(part.router)
