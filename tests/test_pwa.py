"""Installable, and readable with no network.

What is offline-capable here is reading: the shell, the pages already visited
and their thumbnails. Writing needs the server, and these tests pin that
distinction rather than papering over it.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
SW = ROOT / "dealgo" / "web" / "ts" / "sw.ts"


@pytest.fixture
def client(db, monkeypatch):
    from dealgo import scheduler
    from dealgo.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with TestClient(web_app.app) as test_client:
        yield test_client


# -- being installable -----------------------------------------------------


def test_the_manifest_is_served_from_the_root(client):
    """Its scope covers the site, so it cannot hide under /static."""
    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    manifest = json.loads(response.text)
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"


def test_the_manifest_offers_an_icon_of_every_kind_a_phone_asks_for(client):
    manifest = json.loads(client.get("/manifest.webmanifest").text)
    purposes = {icon.get("purpose") for icon in manifest["icons"]}
    sizes = {icon["sizes"] for icon in manifest["icons"]}

    assert "maskable" in purposes      # Android crops to its own shape
    assert {"192x192", "512x512"} <= sizes


def test_every_icon_the_manifest_names_exists(client):
    manifest = json.loads(client.get("/manifest.webmanifest").text)
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200, icon["src"]


def test_the_page_links_the_manifest_and_the_ios_icon(client):
    body = client.get("/").text

    assert '<link rel="manifest" href="/manifest.webmanifest">' in body
    assert 'rel="apple-touch-icon"' in body      # iOS ignores the manifest's
    assert 'name="theme-color"' in body


# -- the service worker ----------------------------------------------------


def test_the_worker_is_served_from_the_root(client):
    """Scope follows the path a worker is served from: under /static it could
    only ever control /static."""
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert response.headers["service-worker-allowed"] == "/"
    assert "listenForWorkerEvents" in response.text


def test_the_worker_is_never_cached_by_the_browser(client):
    """A cached worker is one that cannot be replaced."""
    assert client.get("/sw.js").headers["cache-control"] == "no-cache"


def test_the_worker_is_registered_with_the_build_version(client):
    """The version names the cache, so a deploy retires the old one."""
    body = client.get("/").text

    assert 'name="dealgo-build"' in body
    assert "/sw.js?v=" in (ROOT / "dealgo" / "web" / "ts" / "pwa.ts").read_text()


# -- what the worker actually does -----------------------------------------
#
# Source strings only prove the code says something. These run the compiled
# worker against a stub Cache API and check what it did.

HARNESS = pathlib.Path(__file__).resolve().parent / "sw_harness.js"
needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node is not installed"
)


@pytest.fixture(scope="module")
def worker_report():
    result = subprocess.run(
        ["node", str(HARNESS)], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


@needs_node
def test_the_cache_is_named_after_the_build(worker_report):
    """So a deploy retires what the last one stored."""
    assert worker_report["cacheNames"] == ["dealgo-v1"]


@needs_node
def test_installing_fills_the_shell(worker_report):
    assert len(worker_report["precached"]) >= 10
    assert "/offline" in worker_report["precached"]


@needs_node
def test_a_write_is_never_intercepted(worker_report):
    """Offline or not, the worker does not answer for a POST."""
    assert worker_report["postIntercepted"] is False


@needs_node
def test_a_page_seen_before_comes_back_marked_as_stored(worker_report):
    """Rendered, not refused — and honest about being a stored copy."""
    assert "the feed" in worker_report["storedCopy"]
    assert 'data-offline-copy="1"' in worker_report["storedCopy"]


@needs_node
def test_a_page_never_seen_says_which_page_it_was(worker_report):
    """"Something went wrong" is no use; the path is."""
    assert "/channels/9" in worker_report["missingPage"]


@needs_node
def test_an_uncached_thumbnail_becomes_a_drawn_placeholder(worker_report):
    """A broken-image icon says nothing. This keeps the card's shape and
    explains itself."""
    placeholder = worker_report["placeholder"]

    assert placeholder["status"] == 200
    assert placeholder["type"] == "image/svg+xml"
    assert placeholder["marked"] == "1"
    assert "not loaded" in placeholder["body"]


@needs_node
def test_nothing_is_substituted_when_there_is_a_network(worker_report):
    assert worker_report["online"] == "live from the server"


# -- the page's own indicators ---------------------------------------------


def test_the_offline_page_leaves_room_for_the_path(client):
    """The worker fills this in with the page that could not be reached."""
    assert "<!--OFFLINE-PATH-->" in client.get("/offline").text


def test_every_page_can_say_it_is_a_stored_copy(client):
    body = client.get("/").text
    notice = body.split('id="stored-copy-notice"', 1)[1].split(">", 1)[0]

    assert "hidden" in notice
    assert "Stored copy" in body


def test_a_panel_that_cannot_refresh_keeps_what_it_has(client):
    """Letting htmx swap the failure in would replace readable content with
    nothing. The panel stays and is marked instead."""
    source = (ROOT / "dealgo" / "web" / "ts" / "pwa.ts").read_text()

    assert "htmx:sendError" in source and "htmx:responseError" in source
    assert "event.preventDefault()" in source
    assert "is-unrefreshed" in source


def test_the_unrefreshed_marker_is_visible(client):
    css = client.get("/static/app.css").text
    assert ".is-unrefreshed" in css
    assert "not refreshed" in css


def test_writes_are_left_alone_by_the_worker():
    """A queued write could not produce the right screen: the page that shows
    the result is rendered on the server. So they fail honestly instead."""
    source = SW.read_text()
    assert 'if (event.request.method !== "GET") return;' in source


def test_the_shell_precache_covers_what_the_app_opens_with():
    source = SW.read_text()
    for asset in ["/offline", "/static/app.css", "/static/focus.js", "/manifest.webmanifest"]:
        assert f'"{asset}"' in source


def test_thumbnails_are_cached_so_a_stored_feed_still_looks_like_one():
    source = SW.read_text()
    assert "ytimg.com" in source and "ggpht.com" in source
    assert "imageCacheLimit" in source          # and does not grow forever


def test_live_state_is_never_answered_from_a_cache():
    """A stale health check or status poll is worse than a failed one."""
    source = SW.read_text()
    assert '"/healthz"' in source


# -- the offline page ------------------------------------------------------


def test_the_offline_page_is_a_real_page(client):
    response = client.get("/offline")

    assert response.status_code == 200
    assert "No connection" in response.text


def test_the_offline_page_says_what_still_works(client):
    body = client.get("/offline").text

    assert "already opened" in body
    assert "marking watched" in body      # and what does not


def test_the_page_carries_an_offline_banner_to_raise(client):
    body = client.get("/").text

    assert 'id="offline-banner"' in body
    assert "hidden" in body.split('id="offline-banner"', 1)[1].split(">", 1)[0]


def test_the_buttons_that_reach_the_server_declare_that_they_need_the_network():
    """The mark moved with the act. A run is started from a trigger box on the
    canvas now, so it is those buttons that go quiet when the connection does
    — the header has nothing left to press."""
    script = (ROOT / "dealgo/web/static/graph.js").read_text()
    marked = script.count('needsNetwork')
    assert marked >= 2, f"only {marked} canvas buttons claim to need the server"


def test_the_icons_are_packaged_with_the_app():
    """`web/static/*` in pyproject is not recursive, so the icons need naming
    separately — they were missing from the image until they were."""
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    globs = config["tool"]["setuptools"]["package-data"]["dealgo"]
    assert "web/static/icons/*" in globs
