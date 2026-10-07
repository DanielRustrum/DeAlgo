"""Loading a plugin's file into a runtime of its own, and calling it within its ceilings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import lupa

from .errors import PluginError, PluginStopped, complaint
from .guard import only_what_is_offered, world_for
from .modules import require_for
from .values import to_lua, to_python

#: Most memory one plugin's Lua may hold. Generous for parsing a feed, and
#: far below anything that would trouble the host.
MOST_MEMORY = 16 * 1024 * 1024


#: Lua instructions between tripwire checks. Small enough that a runaway
#: stops in milliseconds, large enough that real work never notices.
CHECK_EVERY = 200_000


#: How many checks one call may pass before it is stopped. A plugin doing
#: honest work over a feed of a few dozen items is nowhere near this.
MOST_CHECKS = 50


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
    #: Everything handed to this plugin that counts what it has done. Each is
    #: put back to nothing at the start of every call, because these budgets
    #: are per call and a capability built once at load would otherwise count
    #: for the life of the process — a plugin allowed four requests would get
    #: four ever, and then quietly do nothing for the rest of the day.
    _meters: list[Any] = field(default_factory=list)

    def call(self, fn: Any, *args: object) -> object:
        """Call one of the plugin's functions and bring the answer home.

        The instruction budget is per call, so a plugin that does a lot of
        small pieces of work is not punished for the total. So is every other
        budget it has, which is what `_meters` is for.
        """
        self._checks[0] = 0
        for meter in self._meters:
            meter.afresh()
        try:
            return to_python(fn(*args))
        except lupa.LuaMemoryError as exc:
            raise PluginStopped(f"{self.name} asked for too much memory") from exc
        except PluginStopped:
            raise
        except lupa.LuaError as exc:
            raise PluginError(f"{self.name}: {complaint(exc)}") from exc

    def table(self, **fields: object) -> Any:
        """A Lua table, for handing structured things in."""
        made = self._lua.table()
        for key, value in fields.items():
            made[key] = value
        return made

    def given(self, value: object) -> Any:
        """Something of ours as something a plugin can walk."""
        return to_lua(self._lua, value)


def load(
    name: str,
    source: str,
    *,
    given: dict[str, object] | Callable[[Any], dict[str, object]] | None = None,
    home: Path | None = None,
) -> tuple[Sandbox, object]:
    """Run a plugin's file once and return it with whatever it returned.

    A plugin is expected to end in ``return { … }``. What that table has to
    contain is not this function's business; it hands back whatever came and
    lets the registry judge it.

    ``given`` may be a function taking the runtime, for capabilities that have
    to build Lua tables to answer with — a Python list handed straight across
    is something `ipairs` cannot walk, which is not an answer.

    ``home`` is the plugin's folder, which `require` reads its other files
    from. None for a plugin with no folder of its own.
    """
    lua = lupa.LuaRuntime(
        register_eval=False,
        register_builtins=False,
        unpack_returned_tuples=True,
        max_memory=MOST_MEMORY,
        attribute_filter=only_what_is_offered,
    )
    checks = [0]

    def tripwire() -> None:
        """Called every `CHECK_EVERY` instructions; stops the plugin past `MOST_CHECKS`."""
        checks[0] += 1
        if checks[0] > MOST_CHECKS:
            raise PluginStopped(f"{name} ran too long and was stopped")

    # The hook has to be a Lua function, and it is set before the plugin's
    # own code runs — from outside the environment the plugin will get, so
    # there is no `debug` in there to switch it back off with.
    lua.globals()["__tripwire"] = tripwire
    lua.execute(f"debug.sethook(function() __tripwire() end, '', {CHECK_EVERY})")

    handing = given(lua) if callable(given) else (given or {})
    env = world_for(lua, handing)
    # Its other files, from its own folder and nowhere else (modules.py).
    env["require"] = require_for(lua, env, home)
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
            raise PluginError(f"{name}: {complaint(why) if why else 'is not readable Lua'}")
    if chunk is None:
        raise PluginError(f"{name}: is not readable Lua")

    box = Sandbox(
        name=name, _lua=lua, _env=env, _checks=checks, _meters=_metered(handing)
    )
    return box, box.call(chunk)


def _metered(given: dict[str, object]) -> list[Any]:
    """Which of the things handed over keep a count that has to be put back.

    Asked of the object rather than listed here, so a capability that starts
    counting something later is reset without this having to hear about it.
    """
    unique = {id(thing): thing for thing in given.values()}  # one thing may go by two names
    return [thing for thing in unique.values() if callable(getattr(thing, "afresh", None))]
