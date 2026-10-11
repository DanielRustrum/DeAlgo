"""How layout boxes and wires look: drawing only, never read by a run.

* A **Relay** faces a way: which side takes the wire in and which gives it
  out — left to right, as boxes do, or any other way round.
* A **group** has a colour — the theme's own, as a comment's are — and can
  be folded up to its name, hiding what it surrounds; a lock holds where it
  is, not whether it is folded.
* A **wire** is drawn as a curve, a straight line, square elbows, or a path
  found round the boxes in its way.

Kept as JSON on the box (`GraphNode.look`) and a word on the wire
(`GraphEdge.route`), read and written only here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ...models import GraphEdge, GraphNode
from .comments import COLOURS
from .errors import GraphError

#: Which way a relay faces: where what it carries comes in, and goes out.
FACES: tuple[tuple[str, str], ...] = (
    ("right", "In on the left, out on the right"),
    ("left", "In on the right, out on the left"),
    ("down", "In at the top, out at the bottom"),
    ("up", "In at the bottom, out at the top"),
)

#: How a wire is drawn.
ROUTES: tuple[tuple[str, str], ...] = (
    ("curve", "Curve"),
    ("straight", "Straight"),
    ("square", "Square"),
    ("astar", "Around boxes"),
)


def look(node: GraphNode) -> dict[str, Any]:
    """What a box's look is set to: the defaults for its kind, and its own."""
    try:
        stored: Any = json.loads(node.look or "{}")
    except ValueError:
        stored = {}
    stored = stored if isinstance(stored, dict) else {}
    if node.kind == "relay":
        faces = str(stored.get("faces") or "right")
        return {"faces": faces if faces in dict(FACES) else "right"}
    if node.kind == "group":
        colour = str(stored.get("colour") or "paper")
        return {
            "colour": colour if colour in dict(COLOURS) else "paper",
            "collapsed": bool(stored.get("collapsed")),
        }
    return {}


def save(node: GraphNode, form: Mapping[str, str]) -> None:
    """Set a box's look from `look_faces`, `look_colour` and `look_collapsed`;
    one left out is left as it was."""
    said = look(node)
    if not said:
        return
    faces = form.get("look_faces")
    if faces is not None and "faces" in said:
        if faces not in dict(FACES):
            raise GraphError("A relay faces left, right, up or down.")
        said["faces"] = faces
    colour = form.get("look_colour")
    if colour is not None and "colour" in said:
        if colour not in dict(COLOURS):
            raise GraphError("A group comes in the theme's colours: paper, sage, blush, ochre or sky.")
        said["colour"] = colour
    collapsed = form.get("look_collapsed")
    if collapsed is not None and "collapsed" in said:
        said["collapsed"] = collapsed == "1"
    node.look = json.dumps(said, sort_keys=True)


def route_of(edge: GraphEdge) -> str:
    return edge.route if edge.route in dict(ROUTES) else "curve"


def set_route(edge: GraphEdge, route: str) -> None:
    """Draw a wire another way."""
    if route not in dict(ROUTES):
        raise GraphError("A wire is drawn as a curve, straight, square, or round the boxes.")
    edge.route = None if route == "curve" else route
