"""What a browser needs to install and run the app: the worker, the manifest, offline, health."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ... import __version__
from ...services import sync as sync_service
from ..responses import render
from ..templates import BASE_DIR

if TYPE_CHECKING:
    pass

router = APIRouter()


@router.get("/sw.js")
def service_worker() -> Response:
    """The service worker, served from the root.

    Scope is decided by where a worker is served from, so this cannot live
    under /static: a worker fetched from /static/sw.js could only control
    /static. Never cached by the browser, or a new one could not replace it.
    """
    worker = BASE_DIR / "static" / "sw.js"
    if not worker.exists():  # pragma: no cover - only if the build was skipped
        return Response("", status_code=404)
    return Response(
        worker.read_text(),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@router.get("/manifest.webmanifest")
def web_manifest() -> Response:
    """Served from the root so its scope covers the whole site."""
    manifest = BASE_DIR / "static" / "manifest.webmanifest"
    return Response(
        manifest.read_text(),
        media_type="application/manifest+json",
        headers={"Cache-Control": "max-age=3600"},
    )


@router.get("/offline", response_class=HTMLResponse)
def offline(request: Request) -> HTMLResponse:
    """What the worker shows for a page that has never been loaded.

    Precached on install, so it is there exactly when nothing else is.
    """
    return render(request, "offline.html", {})


@router.get("/healthz")
def healthz() -> dict[str, object]:
    """Liveness for the container: always ok, with the version and whether a run is going."""
    return {"status": "ok", "version": __version__, "syncing": sync_service.is_running()}
