"""`require`: a plugin's other files, from its own folder and nowhere else.

A plugin is a folder with `plugin.lua` in it, and `plugin.lua` is where it
starts. Anything bigger than a page can be split across more `.lua` files
beside it and pulled in with `require("parse")` or `require("lib.dates")` —
the dots are folders, as in ordinary Lua.

This is not Lua's own `require`, which searches a path and can load C. This
one reads a file only if it is a `.lua` file inside the plugin's folder, runs
it in the plugin's own world (its same globals, its same limits), and keeps
what it returned, so a module is run once however many files ask for it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

#: The plugin's entry file. Not something to require: it is already running.
ENTRY = "plugin.lua"

#: What one module file may weigh, the same ceiling as a whole uploaded plugin.
MOST_MODULE_BYTES = 256 * 1024

#: How many different modules one plugin may load. A few dozen is a large
#: plugin; hundreds is something other than a plugin.
MOST_MODULES = 64

#: A module name: words of letters, digits and underscores, joined by dots.
#: Nothing that could climb out of the folder — no slashes, no `..`.
NAME = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*")

#: The Lua half. Made outside the plugin's world, so the `load` it closes over
#: is the host's, and handed the plugin's environment so every module runs in
#: it. A module that requires itself, directly or round a loop, is an error
#: rather than a stack overflow.
REQUIRE = """
function(env, read)
  local loaded, loading = {}, {}
  return function(name)
    if type(name) ~= "string" then
      error("require takes a module name, like require(\\"parse\\")", 2)
    end
    if loaded[name] ~= nil then return loaded[name] end
    if loading[name] then error("“" .. name .. "” requires itself", 2) end
    local source, why = read(name)
    if not source then error(why, 2) end
    local chunk, problem = load(source, "@" .. name:gsub("%.", "/") .. ".lua", "t", env)
    if not chunk then error(problem, 0) end
    loading[name] = true
    local made = chunk(name)
    loading[name] = nil
    if made == nil then made = true end
    loaded[name] = made
    return made
  end
end
"""


def reader(home: Path | None) -> Callable[[object], tuple[str | None, str | None]]:
    """What `require` reads a module's source with, for a plugin living in `home`.

    Answers `(source, None)` or `(None, why)`, which Lua receives as two
    values. `home` is None for a plugin with no folder of its own — one
    uploaded as a single file and not yet kept — and then every module is
    missing, with a sentence saying why.
    """
    seen: set[str] = set()
    root = home.resolve() if home is not None else None

    def read(asked: object) -> tuple[str | None, str | None]:
        name = str(asked)
        if not NAME.fullmatch(name):
            return None, f"“{name}” is not a module name: letters, digits, _ and dots only"
        if root is None or not root.is_dir():
            return None, (
                f"cannot require “{name}”: only a plugin in a folder of its own "
                "has other files to require"
            )
        path = (root / (name.replace(".", "/") + ".lua")).resolve()
        if root not in path.parents:
            return None, f"“{name}” is outside the plugin's folder"
        if path.name == ENTRY and path.parent == root:
            return None, f"“{name}” is the plugin's own entry file, which is already running"
        if name not in seen and len(seen) >= MOST_MODULES:
            return None, f"a plugin may load at most {MOST_MODULES} modules"
        if not path.is_file():
            return None, f"there is no {name.replace('.', '/')}.lua in the plugin's folder"
        if path.stat().st_size > MOST_MODULE_BYTES:
            return None, f"{name.replace('.', '/')}.lua is over {MOST_MODULE_BYTES // 1024} KiB"
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None, f"{name.replace('.', '/')}.lua could not be read as text"
        seen.add(name)
        return source, None

    return read


def require_for(lua: Any, env: Any, home: Path | None) -> Any:
    """The `require` function to put in a plugin's world."""
    return lua.eval(REQUIRE)(env, reader(home))
