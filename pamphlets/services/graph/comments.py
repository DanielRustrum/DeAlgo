"""Comments: notes left on the canvas, for whoever reads it next.

A Comment box carries words and nothing else: it is wired to nothing, runs
nothing, and is wherever it was put — in a canvas, in a group. Its words and
colour are kept as JSON in one column (`GraphNode.comment`), read and written
only here; its size is the width and height a group has.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from ...models import GraphNode
from ..scope import OwnerId
from .errors import GraphError

#: The colours a comment can be: the theme's own, so they follow it.
COLOURS: tuple[tuple[str, str], ...] = (
    ("paper", "Paper"), ("sage", "Sage"), ("blush", "Blush"), ("ochre", "Ochre"), ("sky", "Sky"),
)
#: What a comment starts as, and the least it can be shrunk to.
SIZE = (260, 140)
LEAST = (140, 60)
#: The most words one holds.
MOST_TEXT = 10_000


def settings(node: GraphNode) -> dict[str, str]:
    """A comment's words and colour."""
    try:
        stored: Any = json.loads(node.comment or "{}")
    except ValueError:
        stored = {}
    stored = stored if isinstance(stored, dict) else {}
    colour = str(stored.get("colour") or "paper")
    return {
        "text": str(stored.get("text") or ""),
        "colour": colour if colour in dict(COLOURS) else "paper",
    }


def save(node: GraphNode, form: Mapping[str, str]) -> None:
    """Set a comment's words and colour from `comment_text` and
    `comment_colour`; one left out is left as it was."""
    said = settings(node)
    text = form.get("comment_text")
    if text is not None:
        said["text"] = str(text)[:MOST_TEXT]
    colour = form.get("comment_colour")
    if colour is not None:
        if colour not in dict(COLOURS):
            raise GraphError("A comment comes in the theme's colours: paper, sage, blush, ochre or sky.")
        said["colour"] = colour
    node.comment = json.dumps(said, sort_keys=True)


def add_comment(
    session: Session, owner: OwnerId = None, *, text: str = "", x: int = 0, y: int = 0,
) -> GraphNode:
    """A Comment box where it was dropped, ready to be written in."""
    node = GraphNode(owner_pk=owner, kind="comment", label="", x=x, y=y, width=SIZE[0], height=SIZE[1])
    node.comment = json.dumps({"text": text[:MOST_TEXT], "colour": "paper"}, sort_keys=True)
    session.add(node)
    session.flush()
    return node
