"""The admin's plugins page: adding, fetching, granting, pausing and removing."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select

from ... import outgoing
from ...db import session_scope
from ...models import (
    Channel,
)
from ...plugins import fetching, permissions, registry
from ..responses import redirect, render
from ..templates import Context

router = APIRouter()


#: What a plugin file may weigh. A source plugin is a page or two of Lua; a
#: megabyte of it is somebody uploading the wrong thing.
MOST_PLUGIN_BYTES = 256 * 1024


@router.get("/admin/plugins", response_class=HTMLResponse)
def plugins_page(request: Request) -> HTMLResponse:
    """The admin's Plugins page."""
    return _plugins_view(request)


def _plugins_view(request: Request, pending: Context | None = None) -> HTMLResponse:
    """The page, optionally with a plugin waiting to be agreed to."""
    found = registry.current()
    mine = registry.storage.folder()
    leaning = _sources_per_kind()
    came_from = registry.origins()
    return render(
        request,
        "plugins.html",
        {
            "plugins": [
                {
                    "id": plugin.id,
                    "title": plugin.title,
                    "version": plugin.version,
                    "ok": plugin.ok,
                    "loaded": plugin.loaded,
                    "paused": plugin.paused,
                    "trouble": plugin.trouble,
                    "sources": plugin.sources,
                    "wants": plugin.wants,
                    "granted": plugin.granted,
                    "wanting": plugin.wanting,
                    "path": plugin.path,
                    "replaces": plugin.replaces,
                    # Only a plugin of one's own can be removed from here.
                    # A shipped one comes back with the next start anyway,
                    # so a Remove button on it would be a lie — pausing is
                    # how you turn one of those off.
                    "mine": plugin.home.parent == mine,
                    # Where it was fetched from, when it was. Shown so that
                    # "where did this come from" is answerable without
                    # remembering, and so it can be fetched again.
                    "origin": came_from.get(plugin.id),
                    # How much is leaning on it, so switching one off is a
                    # decision rather than a discovery.
                    "leaning": sum(leaning.get(k.kind, 0) for k in plugin.sources),
                }
                for plugin in found.plugins
            ],
            "folder": mine,
            "pending": pending,
            "known_permissions": permissions.KNOWN,
        },
    )


def _sources_per_kind() -> dict[str, int]:
    """How many watched sources each kind accounts for, across every account.

    Install-wide, because a plugin is: switching one off reaches everybody,
    and the admin deciding that should be able to see the whole cost.
    """
    with session_scope() as session:
        rows = session.execute(
            select(Channel.source_kind, func.count(Channel.id)).group_by(Channel.source_kind)
        )
        return {kind: count for kind, count in rows}


@router.post("/admin/plugins/{plugin_id}/pause")
def pause_plugin(request: Request, plugin_id: str, on: str = Form("")) -> Response:
    """Switch a plugin off, or back on.

    The only way to turn off one that ships in the image, and gentler than
    removing one of your own: nothing is deleted, and what it offered comes
    back the moment it is switched on again.
    """
    if not set(plugin_id) <= registry.PLAIN:
        return redirect("/admin/plugins", err="That is not a plugin here.")
    found = next((p for p in registry.current().plugins if p.id == plugin_id), None)
    if found is None:
        return redirect("/admin/plugins", err="That is not a plugin here.")

    wanted = on == "1"
    registry.set_paused(plugin_id, paused=not wanted)
    if wanted:
        return redirect("/admin/plugins", ok=f"{found.title} switched on.")
    return redirect(
        "/admin/plugins",
        ok=f"{found.title} switched off. What it recognised is no longer recognised; "
        "sources already being watched keep their own feed address and carry on.",
    )


@router.post("/admin/plugins")
async def add_plugin(request: Request, file: UploadFile = File(...)) -> Response:
    """Take a .lua file into the plugins folder.

    Adding a plugin is adding code that runs in this process. It is walled
    off — no files, no network, no credentials — but it reads every reference
    anybody adds, so this is deliberately an admin-only door and says so on
    the page rather than pretending it is an ordinary upload.
    """
    given = (file.filename or "").strip()
    # Refused rather than quietly reduced to its last part. Stripping a
    # "../" would be safe and would also mean somebody's file landing under a
    # name they did not choose, which is a worse thing to be surprised by
    # than an error.
    if not given or given != Path(given).name:
        return redirect("/admin/plugins", err="Give it a plain filename, with no path in it.")
    name = given
    if not name.endswith(".lua"):
        return redirect("/admin/plugins", err="A plugin is a .lua file.")
    stem = name[: -len(".lua")]
    if not stem or not set(stem) <= registry.PLAIN:
        return redirect(
            "/admin/plugins",
            err="Name it with letters, numbers, dashes or underscores — it becomes its id.",
        )

    body = await file.read(MOST_PLUGIN_BYTES + 1)
    if len(body) > MOST_PLUGIN_BYTES:
        return redirect("/admin/plugins", err="That file is far too big to be a plugin.")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return redirect("/admin/plugins", err="That file is not text.")

    # Read it before keeping it, with nothing granted. A plugin that will not
    # load is a plugin nobody wants in the folder, and saying so now beats a
    # broken row later.
    checked = registry.judge(stem, text)
    if checked.trouble:
        return redirect("/admin/plugins", err=f"{name}: {checked.trouble}")

    # Nothing is written yet. What it asks for is put to somebody first, and
    # the file lands only once they have said yes — so a plugin nobody agreed
    # to is never on disk at all.
    return _plugins_view(request, pending={"name": name, "source": text, "plugin": checked})


@router.post("/admin/plugins/fetch")
def fetch_plugin(request: Request, url: str = Form(""), ref: str = Form("")) -> Response:
    """Take a plugin out of a git repository, and put it to somebody.

    The same door as an upload, reached a different way: what comes back is
    text, it is read with nothing granted, and it lands only once its
    permissions have been agreed to. Fetching is not installing.
    """
    wanted = (ref or "").strip()
    if len(wanted) > 120 or any(one.isspace() for one in wanted):
        return redirect("/admin/plugins", err="That is not a branch or tag name.")

    try:
        with outgoing.client() as http:
            got = fetching.fetch(url, http, ref=wanted)
    except registry.PluginError as exc:
        return redirect("/admin/plugins", err=str(exc))

    if not got.plugin_id or not set(got.plugin_id) <= registry.PLAIN:
        return redirect(
            "/admin/plugins",
            err="That repository's name cannot be a plugin id. Rename it to "
                "letters, numbers, dashes or underscores.",
        )
    if len(got.source.encode("utf-8")) > MOST_PLUGIN_BYTES:
        return redirect("/admin/plugins", err="That plugin.lua is far too big to be one.")

    # Read before it is kept, with nothing granted, exactly as an upload is.
    checked = registry.judge(got.plugin_id, got.source)
    if checked.trouble:
        return redirect("/admin/plugins", err=f"{got.plugin_id}: {checked.trouble}")

    # Held aside while somebody decides. A plugin may be more than one file,
    # and what was read and judged here is then exactly what lands — a second
    # fetch on the way past consent would leave a gap in which the repository
    # could become something else.
    try:
        registry.stage(got.plugin_id, got.source, got.extras)
    except (OSError, registry.PluginError) as exc:
        return redirect("/admin/plugins", err=f"Could not be saved: {exc}")

    return _plugins_view(
        request,
        pending={
            "name": f"{got.plugin_id}.lua",
            "source": got.source,
            "plugin": checked,
            "origin": got.origin,
            "ref": got.ref,
            "extras": sorted(got.extras),
        },
    )


@router.post("/admin/plugins/confirm")
async def confirm_plugin(
    request: Request,
    name: str = Form(""),
    source: str = Form(""),
    origin: str = Form(""),
    ref: str = Form(""),
) -> Response:
    """Keep a plugin, with exactly the permissions that were ticked.

    Read again rather than trusted from the form: what is judged has to be
    what lands, and the only thing carried across is the file itself.
    """
    stem = name[: -len(".lua")] if name.endswith(".lua") else ""
    if not stem or not set(stem) <= registry.PLAIN or len(source) > MOST_PLUGIN_BYTES:
        return redirect("/admin/plugins", err="That was not a plugin this page offered.")

    checked = registry.judge(stem, source)
    if checked.trouble:
        return redirect("/admin/plugins", err=f"{name}: {checked.trouble}")

    sent = await request.form()
    # Only what it asked for: a tick for something it never wanted cannot
    # grant it, whatever the form says.
    wanted = {want.name for want in checked.wants if want.known}
    granting = frozenset(name for name in wanted if sent.get(f"grant_{name}") == "1")

    try:
        # A fetched one is already on disk, waiting: taking it is a rename,
        # and it brings whatever else came with it. An uploaded one is the
        # file in front of us and nothing else.
        if not (origin and registry.take_staged(stem)):
            registry.keep(stem, source)
    except (OSError, registry.PluginError) as exc:  # a full or unwritable volume
        return redirect("/admin/plugins", err=f"Could not be saved: {exc}")

    if origin:
        # Where it came from, so the Update button has somewhere to go. Kept
        # against the id rather than in the folder: a plugin that could write
        # its own origin could point its next update at somewhere else.
        registry.set_origin(stem, origin[:2000], ref[:120])
    registry.set_granted(stem, granting)
    said = f"{checked.title} added"
    if granting:
        labels = ", ".join(sorted(permissions.describe(n).label.lower() for n in granting))
        said += f", allowed to {labels}"
    elif checked.wants:
        said += ", with none of what it asked for"
    return redirect("/admin/plugins", ok=said + ".")


@router.post("/admin/plugins/{plugin_id}/permissions")
async def set_plugin_permissions(request: Request, plugin_id: str) -> Response:
    """Change what a plugin already here is allowed to do."""
    if not set(plugin_id) <= registry.PLAIN:
        return redirect("/admin/plugins", err="That is not a plugin here.")
    found = next((p for p in registry.current().plugins if p.id == plugin_id), None)
    if found is None:
        return redirect("/admin/plugins", err="That is not a plugin here.")

    sent = await request.form()
    wanted = {want.name for want in found.wants if want.known}
    granting = frozenset(name for name in wanted if sent.get(f"grant_{name}") == "1")
    registry.set_granted(plugin_id, granting)

    gained = granting - found.granted
    lost = found.granted - granting
    if not gained and not lost:
        return redirect("/admin/plugins", ok=f"{found.title} is unchanged.")
    return redirect(
        "/admin/plugins",
        ok=f"{found.title} now has {len(granting)} of the "
        f"{len(wanted)} thing{'s' if len(wanted) != 1 else ''} it asked for.",
    )


@router.post("/admin/plugins/{plugin_id}/remove")
def remove_plugin(request: Request, plugin_id: str) -> Response:
    """Take one of your own out of the folder.

    Only your own: a shipped plugin lives in the image and would come back on
    the next start, so a button offering to remove one would be a lie.
    """
    if not registry.discard(plugin_id):
        return redirect("/admin/plugins", err="That is not a plugin you added.")
    registry.reload()
    return redirect("/admin/plugins", ok=f"{plugin_id} removed.")
