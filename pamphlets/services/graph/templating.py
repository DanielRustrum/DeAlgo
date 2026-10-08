"""`{{ field }}` in a setting: a field of the data, beside static text.

A setting that names a field — where a chart's label is, the number it
shows — is written `{{ data.author }}`, the way the editor puts it there
when a field is dragged in; one written before that, as a bare path, still
reads the same. A setting that is words — a heading, what a Text box is
told — can mix the two: `Videos this week: {{ count }}`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ...sources import rest

#: One field, written between double braces, with or without spaces inside.
FIELD = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")


def path_of(setting: Any) -> str:
    """The field a path setting names: what is between the braces, or — for
    a setting from before there were braces — the whole of it."""
    text = str(setting or "").strip()
    found = FIELD.search(text)
    return found.group(1) if found is not None else text


def fill(text: str, data: Any) -> str:
    """Words with each `{{ field }}` replaced by that field of the data.

    The field is looked for in the data as it is, then in its first row, so
    `{{ count }}` reads a count and `{{ title }}` the first item's title.
    One that is not there is left blank.
    """
    if "{{" not in text:
        return text
    first = _first_row(data)

    def value(match: re.Match[str]) -> str:
        path = match.group(1)
        found = _walk(data, path)
        if found is None and first is not None:
            found = _walk(first, path)
        return _written(found)

    return FIELD.sub(value, text)


def _first_row(data: Any) -> Any:
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        try:
            rows = rest.locate(data, "")[0]
        except rest.RestError:
            return None
        return rows[0] if rows else None
    return None


def _walk(data: Any, path: str) -> Any:
    if not path or not isinstance(data, (dict, list)):
        return None
    try:
        return rest.walk(data, path)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _written(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float) and value.is_integer():
        return f"{value:,.0f}"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)
