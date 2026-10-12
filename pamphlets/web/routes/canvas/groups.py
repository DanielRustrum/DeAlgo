"""Handing a canvas to somebody else as a .pam file, and taking one in.

A Canvas box is saved as a file — everything inside it. Groups are not any
more; a group file saved before still loads, and a group loaded from one can
still be brought up to date from a newer copy."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from ....db import session_scope
from ....services import graph as graph_service
from ...responses import owner_of

if TYPE_CHECKING:
    pass
from .payload import graph_payload

router = APIRouter()


@router.get("/graph/nodes/{node_pk}/export")
def graph_export_canvas(request: Request, node_pk: int) -> Response:
    """A Canvas box, and everything inside it, as a .pam file."""
    owner = owner_of(request)
    with session_scope() as session:
        try:
            packed = graph_service.canvas_files.export_canvas(session, node_pk, owner)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    name = re.sub(r"[^A-Za-z0-9]+", "-", str(packed["name"])).strip("-").lower() or "canvas"
    return Response(
        content=json.dumps(packed, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}{graph_service.canvas_files.SUFFIX}"'},
    )


@router.post("/graph/groups")
async def graph_import_group(
    request: Request, file: UploadFile = File(...), x: int = Form(40), y: int = Form(40),
    anyway: str = Form(""),
) -> JSONResponse:
    """Load a .pam canvas file — or a group file saved before groups gave
    way to canvases — into the canvas being worked in. Nothing existing is
    changed.

    A canvas file whose boxes are from plugins this install does not have
    is not loaded, but answered with which — and whether the person loading
    it may install them — unless they asked to load it `anyway`."""
    owner = owner_of(request)
    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"error": "That file is not readable JSON."}, status_code=400)

    if anyway != "1":
        missing = graph_service.canvas_files.missing_plugins(payload)
        if missing:
            identity = getattr(request.state, "identity", None)
            return JSONResponse(
                {
                    "missing": missing,
                    # Installing is the admin's; with sign-in off, everybody is.
                    "can_install": identity is None or bool(identity.is_admin),
                },
                status_code=409,
            )

    with session_scope() as session:
        try:
            if graph_service.canvas_files.is_canvas_file(payload):
                graph_service.canvas_files.import_canvas(session, payload, owner, x=x, y=y)
            else:
                graph_service.import_group(
                    session, payload, owner, x=x, y=y, file_name=file.filename or ""
                )
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(graph_payload(session, owner))


@router.post("/graph/nodes/{node_pk}/update")
async def graph_update_group(
    request: Request, node_pk: int, file: UploadFile = File(...)
) -> JSONResponse:
    """Bring a loaded group up to date with a newer copy of its file.

    Refused, and nothing changed, if the file is a different group from the
    one this was loaded from.
    """
    owner = owner_of(request)
    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"error": "That file is not readable JSON."}, status_code=400)

    with session_scope() as session:
        try:
            result = graph_service.update_group(
                session, node_pk, payload, owner, file_name=file.filename or ""
            )
        except graph_service.GraphError as exc:
            session.rollback()
            return JSONResponse({"error": str(exc)}, status_code=400)
        name = str(payload.get("name") or "Group")
        return JSONResponse({**graph_payload(session, owner), "said": result.describe(name)})
