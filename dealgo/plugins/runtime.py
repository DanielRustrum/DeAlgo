"""Running a plugin's Lua, and keeping it where it is put.

A plugin is somebody else's code running inside this process, so the question
is not "what can it do" but "what is it handed". It is handed a table, and
that table is the whole of its world: no ``io``, no ``os``, no ``require``,
no ``load``, and no way to reach the Python objects behind the functions it
is given.

Three ceilings, because a plugin does not have to be hostile to hang a sync:

* **memory** — a table that grows for ever stops at a few megabytes;
* **instructions** — a loop that never ends stops after a few hundred
  thousand steps, through a debug hook the plugin cannot reach to remove;
* **no network** — the host fetches, so rate limits and patience stay in the
  one place that knows about them.

Nothing here knows what a source or a node is. It loads a file, calls a
function, and turns what comes back into Python. What those functions mean is
``registry``'s business.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import lupa

log = logging.getLogger(__name__)

#: Most memory one plugin's Lua may hold. Generous for parsing a feed, and
#: far below anything that would trouble the host.
MOST_MEMORY = 16 * 1024 * 1024

#: Lua instructions between tripwire checks. Small enough that a runaway
#: stops in milliseconds, large enough that real work never notices.
CHECK_EVERY = 200_000

#: How many checks one call may pass before it is stopped. A plugin doing
#: honest work over a feed of a few dozen items is nowhere near this.
MOST_CHECKS = 50

#: What a plugin's own code may see. Everything here is pure: it computes,
#: it cannot reach out, and it cannot look at the host.
ALLOWED = (
    "assert", "error", "ipairs", "next", "pairs", "pcall", "select",
    "tonumber", "tostring", "type", "unpack", "xpcall",
)
ALLOWED_MODULES = ("string", "table", "math")


class PluginError(RuntimeError):
    """Something a plugin did wrong, said the way its author would want it."""


class PluginStopped(PluginError):
    """It ran too long, or asked for too much memory, and was stopped."""


@dataclass
class Sandbox:
    """One plugin's Lua, already loaded and ready to be called.

    One runtime per plugin rather than one shared: a plugin that fills its
    memory or trips its instruction limit should take nobody else down with
    it, and two plugins should not be able to see each other's globals.
    """

    name: str
    _lua: Any
    _env: Any
    _checks: list[int] = field(default_factory=lambda: [0])

    def call(self, fn: Any, *args: object) -> object:
        """Call one of the plugin's functions and bring the answer home.

        The instruction budget is per call, so a plugin that does a lot of
        small pieces of work is not punished for the total.
        """
        self._checks[0] = 0
        try:
            return _plain(fn(*args))
        except lupa.LuaMemoryError as exc:
            raise PluginStopped(f"{self.name} asked for too much memory") from exc
        except PluginStopped:
            raise
        except lupa.LuaError as exc:
            raise PluginError(f"{self.name}: {_complaint(exc)}") from exc

    def table(self, **fields: object) -> Any:
        """A Lua table, for handing structured things in."""
        made = self._lua.table()
        for key, value in fields.items():
            made[key] = value
        return made


def load(
    name: str,
    source: str,
    *,
    given: dict[str, object] | Callable[[Any], dict[str, object]] | None = None,
) -> tuple[Sandbox, object]:
    """Run a plugin's file once and return it with whatever it returned.

    A plugin is expected to end in ``return { … }``. What that table has to
    contain is not this function's business; it hands back whatever came and
    lets the registry judge it.

    ``given`` may be a function taking the runtime, for capabilities that have
    to build Lua tables to answer with — a Python list handed straight across
    is something `ipairs` cannot walk, which is not an answer.
    """
    lua = lupa.LuaRuntime(
        register_eval=False,
        register_builtins=False,
        unpack_returned_tuples=True,
        max_memory=MOST_MEMORY,
    )
    checks = [0]

    def tripwire() -> None:
        checks[0] += 1
        if checks[0] > MOST_CHECKS:
            raise PluginStopped(f"{name} ran too long and was stopped")

    # The hook has to be a Lua function, and it is set before the plugin's
    # own code runs — from outside the environment the plugin will get, so
    # there is no `debug` in there to switch it back off with.
    lua.globals()["__tripwire"] = tripwire
    lua.execute(f"debug.sethook(function() __tripwire() end, '', {CHECK_EVERY})")

    handing = given(lua) if callable(given) else (given or {})
    env = _world(lua, handing)
    try:
        chunk = lua.eval("function(src, name, env) return load(src, name, 't', env) end")(
            source, f"@{name}", env
        )
    except lupa.LuaError as exc:  # pragma: no cover - a broken host, not a plugin
        raise PluginError(f"{name}: could not be prepared: {exc}") from exc
    # `load` answers with the chunk, or with nil and why — and because this
    # runtime unpacks returned tuples, a refusal arrives as a pair. Saying
    # what Lua disliked is the whole value of the message.
    if isinstance(chunk, tuple):
        chunk, why = (chunk + (None, None))[:2]
        if chunk is None:
            raise PluginError(f"{name}: {_complaint(why) if why else 'is not readable Lua'}")
    if chunk is None:
        raise PluginError(f"{name}: is not readable Lua")

    box = Sandbox(name=name, _lua=lua, _env=env, _checks=checks)
    return box, box.call(chunk)


def _world(lua: Any, given: dict[str, object]) -> Any:
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


def _complaint(exc: BaseException) -> str:
    """What Lua said, without the parts only Lua cares about.

    A Lua error carries a stack traceback and repeats the chunk name it was
    given. Neither helps the person reading the plugin list; the line number
    and the message do.
    """
    said = str(exc).split("stack traceback:")[0].strip()
    # Lua writes "@name:12: message"; the name is already on the row.
    _, _, after = said.partition(":")
    return (after.strip() or said) if said.count(":") >= 2 else said


def _plain(value: object) -> object:
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
        return [_plain(table[key]) for key in keys]
    return {str(key): _plain(table[key]) for key in keys}
