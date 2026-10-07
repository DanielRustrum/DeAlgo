"""Reading the JSON a page carries inside itself.

Some sources have no feed and no API, and the only place their content exists
is a blob of JSON a page assigns to a variable for its own scripts to read.
Pulling that out is the same kind of work as parsing XML: a real parser, doing
a generic job, which is why it lives here and not in a plugin.

Nothing here knows which site it is reading. A plugin says which variable and
which key; this finds them. What comes back is whatever that page had in it —
unchecked, because it is somebody else's data, and shaped however they felt
like shaping it today.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterator

log = logging.getLogger(__name__)

#: How deep to go looking. A page cannot nest meaningfully further than this,
#: and a cycle-free walk is only guaranteed while there is a floor under it.
DEEPEST = 60

#: How many matches to hand back. A page with more than this under one key is
#: not a page anybody meant to read.
MOST_MATCHES = 500


def script_object(html: str, name: str) -> Any:
    """The JSON object a page assigns to `name`, decoded.

    ``var ytInitialData = {…};`` and its cousins. Matched rather than parsed
    as JavaScript, because the assignment is always one statement and writing
    a JavaScript parser to read one of them would be absurd.

    Nothing on failure. A page that changed shape should give a plugin
    nothing to work with, not an exception in the middle of a sync.
    """
    if not html or not name:
        return None
    # Find `name = {`, then read to the brace that closes it.
    pattern = re.compile(
        r"(?:var|let|const)?\s*" + re.escape(name) + r"\s*=\s*(\{)", re.S
    )
    match = pattern.search(html)
    if match is None:
        log.debug("no %s in the page", name)
        return None

    text = _balanced(html, match.start(1))
    if text is None:
        log.debug("%s was not closed", name)
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.debug("%s did not parse as JSON", name)
        return None


def find(value: Any, key: str, *, most: int = MOST_MATCHES) -> list[Any]:
    """Every value stored under `key`, however deep.

    Searched rather than addressed by a path, because the shape of these blobs
    shifts between the layouts a site serves and a path that worked yesterday
    is a path that finds nothing today.
    """
    found: list[Any] = []
    for hit in _walk(value, key, 0):
        found.append(hit)
        if len(found) >= most:
            break
    return found


def _walk(node: Any, key: str, depth: int) -> Iterator[Any]:
    """Every value under `key`, anywhere in `node`, no deeper than `DEEPEST`."""
    if depth > DEEPEST:
        return
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key:
                yield value
            else:
                yield from _walk(value, key, depth + 1)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value, key, depth + 1)


def _balanced(text: str, start: int) -> str | None:
    """From an opening brace to the one that closes it.

    Counting depth rather than matching to the first ``};``, because the blob
    holds post text and a post can hold a brace. Strings are tracked so a
    brace inside one is not counted, and an escape is skipped whole.
    """
    depth = 0
    inside = False
    escaped = False
    for index in range(start, len(text)):
        letter = text[index]
        # Inside a string only an unescaped quote matters; braces in it are text.
        if inside:
            if escaped:
                escaped = False
            elif letter == "\\":
                escaped = True
            elif letter == '"':
                inside = False
            continue
        # Outside a string, count braces until the one we started at is closed.
        if letter == '"':
            inside = True
        elif letter == "{":
            depth += 1
        elif letter == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None
