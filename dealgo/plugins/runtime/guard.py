"""What a plugin may see: its globals, and the attributes of what it is handed."""

from __future__ import annotations

from typing import Any

#: What a plugin's own code may see. Everything here is pure: it computes,
#: it cannot reach out, and it cannot look at the host.
ALLOWED = (
    "assert", "error", "ipairs", "next", "pairs", "pcall", "select",
    "tonumber", "tostring", "type", "unpack", "xpcall",
)


ALLOWED_MODULES = ("string", "table", "math")


def only_what_is_offered(thing: object, name: object, setting: bool) -> str:
    """What a plugin may reach on a Python object it has been handed.

    Only the names that object's class says it offers, and only for reading.
    Everything else raises, including every dunder — which is the one that
    matters, because `__class__` leads to `__globals__`, `__globals__` leads
    to `__builtins__`, and `__builtins__` leads out of the sandbox entirely.

    An object with no list offers nothing. That is the safe default: a
    capability added later without one is inert rather than wide open.
    """
    asked = str(name)
    if setting:
        raise AttributeError(f"a plugin may not set {asked!r}")
    offered: frozenset[str] = getattr(type(thing), "LUA_OFFERS", frozenset())
    if asked in offered:
        return asked
    raise AttributeError(f"a plugin may not read {asked!r}")


def world_for(lua: Any, given: dict[str, object]) -> Any:
    """The table a plugin gets as its entire set of globals."""
    globals_ = lua.globals()
    env = lua.table()
    for word in ALLOWED:
        env[word] = globals_[word]
    for module in ALLOWED_MODULES:
        env[module] = globals_[module]
    # Its own name for its own globals, so `_G.x = 1` works and reaches only
    # this table. Anything it sets is its own and dies with it.
    env["_G"] = env
    for word, thing in given.items():
        env[word] = thing
    return env
