"""Handing a group to somebody else, and taking one in."""

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
def graph_export_group(request: Request, node_pk: int) -> Response:
    """A group as a file to hand somebody else."""
    owner = owner_of(request)
    with session_scope() as session:
        try:
            packed = graph_service.export_group(session, node_pk, owner)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    name = re.sub(r"[^A-Za-z0-9]+", "-", str(packed["name"])).strip("-").lower() or "group"
    return Response(
        content=json.dumps(packed, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="de-algo-{name}.json"'},
    )


@router.post("/graph/groups")
async def graph_import_group(
    request: Request, file: UploadFile = File(...), x: int = Form(40), y: int = Form(40)
) -> JSONResponse:
    """Load a group somebody else exported. Nothing existing is changed."""
    owner = owner_of(request)
    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"error": "That file is not readable JSON."}, status_code=400)

    with session_scope() as session:
        try:
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
