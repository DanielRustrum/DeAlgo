"""What goes into a box and what comes out of it, for the canvas's editor.

The editor shows a box the way a flow tool does: what arrived on the left,
its settings in the middle, what it gives out on the right — each as a
table, as JSON, or as the fields it has, which can be dragged into a
setting. This module says what one side holds, in a shape the browser can
draw without knowing which box it came from.

Read only. Nothing here changes the graph or polls a source.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import GraphEdge, GraphNode
from ...sources import rest
from ..scope import OwnerId, owned
from . import formatting

#: Rows sent to the browser for a side. The count says how many there were.
MOST_SHOWN = 50
#: Fields listed for a side: the first rows' paths, this many at most.
MOST_FIELDS = 80
#: How far into nested objects the fields go.
DEEPEST = 4

#: Boxes that take items and data alike, and give data.
OPERATIONS = ("filter", "sort", "tag", "decay", "expire")


def wired(session: Session, box: GraphNode, owner: OwnerId, carries: str) -> bool:
    """Whether anything carrying this is wired into a box."""
    return session.scalar(
        owned(select(GraphEdge.id), GraphEdge, owner)
        .where(GraphEdge.target_pk == box.id, GraphEdge.carries == carries)
    ) is not None


def arriving(session: Session, box: GraphNode, owner: OwnerId) -> tuple[Any, str]:
    """What reaches a box, and how: data down its { } wire if it has one,
    else the items down its ▶ wires read as rows. ("", None) for nothing."""
    if wired(session, box, owner, "data"):
        return formatting.data_into(session, box, owner), "data"
    if wired(session, box, owner, "content"):
        return formatting.items_into(session, box, owner), "items"
    return None, ""


def side(value: Any, how: str = "data", note: str = "") -> dict[str, Any]:
    """One side of a box, for the editor.

    A list is its rows. An object is the rows found in it, as a Format box
    would find them, with where they were. Anything else is one value.
    """
    value = _plain(value)
    shown: dict[str, Any] = {"how": how, "note": note, "rows": [], "count": 0,
                             "value": None, "found_at": "", "fields": [], "empty": value is None}
    if value is None:
        return shown
    if isinstance(value, dict):
        try:
            rows, where = rest.locate(value, "")
        except rest.RestError:
            rows, where = [value], ""
        shown["found_at"] = where
        value = rows
    if isinstance(value, list):
        shown["count"] = len(value)
        shown["rows"] = value[:MOST_SHOWN]
        shown["fields"] = fields(value)
        return shown
    shown["count"] = 1
    shown["value"] = value
    return shown


def fields(rows: list[Any]) -> list[dict[str, Any]]:
    """Every path in the first rows, with what kind of thing is there and an
    example: what the editor lists, and what can be dragged into a setting."""
    found: dict[str, dict[str, Any]] = {}

    def walk(value: Any, path: str, depth: int) -> None:
        if len(found) >= MOST_FIELDS:
            return
        if isinstance(value, dict) and depth < DEEPEST:
            for key, inner in value.items():
                walk(inner, f"{path}.{key}" if path else str(key), depth + 1)
            return
        if not path:
            return
        seen = found.get(path)
        if seen is None:
            found[path] = {"path": path, "type": _type(value), "sample": _sample(value)}
        elif seen["sample"] in (None, "") and value not in (None, ""):
            seen["type"], seen["sample"] = _type(value), _sample(value)

    for row in rows[:10]:
        walk(row, "", 0)
    return list(found.values())


def _type(value: Any) -> str:
    if value is None:
        return "empty"
    if isinstance(value, bool):
        return "yes/no"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    text = str(value)
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-" and text[:4].isdigit():
        return "date"
    return "text"


def _sample(value: Any) -> Any:
    if isinstance(value, list):
        return f"{len(value)} in it"
    if isinstance(value, dict):
        return f"{len(value)} fields"
    if isinstance(value, str) and len(value) > 80:
        return value[:79] + "…"
    return value


def _plain(value: Any) -> Any:
    """JSON the browser can read: dates and the like as text."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.loads(json.dumps(value, default=str))
