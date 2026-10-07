"""Values crossing between Lua and Python, in both directions.

Tables come back as lists or dicts depending on how they were written, and go
in as Lua tables all the way down — a Python list handed straight across is
something `ipairs` cannot walk.
"""

from __future__ import annotations

from typing import Any

import lupa


def to_python(value: object) -> object:
    """A Lua value as an ordinary Python one.

    Tables come back as lists or dicts depending on how they were written,
    which is the distinction Lua itself does not draw — a table with keys
    1..n and nothing else is a list, and anything else is a mapping.

    Functions are left alone: they are the plugin's, and calling one is the
    sandbox's job rather than this one's.
    """
    if lupa.lua_type(value) != "table":
        return value
    table: Any = value
    keys = list(table.keys())
    if keys and keys == list(range(1, len(keys) + 1)):
        return [to_python(table[key]) for key in keys]
    return {str(key): to_python(table[key]) for key in keys}


def to_lua(lua: Any, value: object) -> Any:
    """Something of ours as something a plugin can walk.

    A Python list handed straight across is not a Lua table and `ipairs`
    finds nothing in it, which is a plugin quietly doing nothing rather than
    a plugin failing — so everything going in is converted, all the way down.
    """
    if isinstance(value, dict):
        made = lua.table()
        for key, inner in value.items():
            made[str(key)] = to_lua(lua, inner)
        return made
    if isinstance(value, (list, tuple)):
        made = lua.table()
        for index, inner in enumerate(value, start=1):
            made[index] = to_lua(lua, inner)
        return made
    return value
