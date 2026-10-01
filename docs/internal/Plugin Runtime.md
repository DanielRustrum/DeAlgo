# Plugin Runtime

`plugins/runtime.py` runs a plugin's Lua with [lupa](https://github.com/scoder/lupa) (Lua 5.5) inside
the app process. It knows nothing about sources or graphs: it loads a file, calls functions, and
converts answers to Python.

## One runtime per plugin

Each plugin gets its own `LuaRuntime`, so one plugin's memory, globals or runaway loop cannot touch
another's. A `Sandbox` holds the runtime, the plugin's environment table and its meters.

```python
lupa.LuaRuntime(
    register_eval=False,          # no python.eval
    register_builtins=False,      # no python.builtins
    unpack_returned_tuples=True,
    max_memory=16 MiB,
    attribute_filter=_only_what_is_offered,
)
```

## The environment

The plugin's file is loaded with `load(source, "@<id>", "t", env)` — **text only** (no bytecode) —
into a fresh table that is its entire world:

| Present | Absent |
| --- | --- |
| `assert error ipairs next pairs pcall select tonumber tostring type xpcall` | `print require load loadfile dofile` |
| `string table math` | `os io debug coroutine utf8 package` |
| `_G` (the env itself) | `setmetatable getmetatable rawget rawset collectgarbage` |
| Capabilities granted: `dealgo` always; `net clock log account` per grant | Any Python object not offered |

(`unpack` is on the allow-list but does not exist in Lua 5.4+; plugins use `table.unpack`.)

## The attribute filter — the one function that matters

A capability is a Python object, and Lua can ask a Python object for any attribute, including
`__class__` → `__globals__` → `__builtins__` → everything. `_only_what_is_offered` allows reading
only names listed in the class's `LUA_OFFERS` and refuses **all** writes. A class without
`LUA_OFFERS` offers nothing, so a new capability is inert until it says what it exposes.

## Ceilings

| Ceiling | Value | Mechanism | On breach |
| --- | --- | --- | --- |
| Memory | 16 MiB | lupa `max_memory` | `PluginStopped` "asked for too much memory" |
| Instructions | 200,000 × 50 = 10 M per call | `debug.sethook` count hook calling a Python tripwire | `PluginStopped` "ran too long" |
| Network | per capability | see [Plugin Registry](Plugin%20Registry.md#capabilities) | Lua error |

The hook is installed **before** the plugin's code runs, from outside its environment, so the
plugin has no `debug` with which to remove it.

## Calling

`Sandbox.call(fn, *args)`:

1. Reset the instruction counter and every capability meter (`afresh()`), so budgets are
   **per call**, not per process.
2. Call; convert the result with `_plain` (a table with keys `1..n` is a list, anything else a
   dict; functions left as Lua functions).
3. Map errors: memory → `PluginStopped`; Lua errors → `PluginError("<name>: <line>: <message>")`
   with the traceback and chunk name trimmed.

`Sandbox.given(value)` converts Python dicts and lists into Lua tables going in, since a Python list
is not walkable with `ipairs`.

## Threading

lupa runtimes are not shared across threads concurrently in practice: syncs are serialised by the
playlist lock, and per-request calls (Test, palette) are short. The `acting_for` owner is
thread-local (see [Plugin Registry](Plugin%20Registry.md#acting-for-an-owner)).

**Related:** [Plugin Registry](Plugin%20Registry.md) ·
[The Sandbox (author's view)](../wiki/Creating%20A%20Plugin/The%20Sandbox.md)
