# The Sandbox

Plugins run in **Lua 5.5**, one sandbox per plugin. A plugin sees only the table it is given.

## Available

| | |
| --- | --- |
| Functions | `assert` `error` `ipairs` `next` `pairs` `pcall` `select` `tonumber` `tostring` `type` `xpcall` |
| Libraries | `string`, `table`, `math` |
| Globals table | `_G` — the plugin's own; setting a global affects only this plugin |
| Capabilities | `dealgo` always; `net`, `clock`, `log`, `account` only if granted — see [Permissions](Permissions.md) |

## Not available

`print`, `require`, `load`, `dofile`, `io`, `os`, `debug`, `coroutine`, `utf8`, `setmetatable`,
`getmetatable`, `rawget`, `rawset`, `_VERSION`.

`unpack` is **not** a global in Lua 5.5 — use `table.unpack`.

Use `log.info` instead of `print` — see [Clock and Log](Clock%20and%20Log.md).

## Limits

| Limit | Value | When exceeded |
| --- | --- | --- |
| Memory per plugin | 16 MiB | *hackernews asked for too much memory* |
| Instructions per call | 10 million | *hackernews ran too long and was stopped* |

The instruction limit counts from zero on every call De-Algo makes into the plugin, and also applies
while the file is first loaded.

## Calling capabilities

Capabilities are host objects. Call their functions with a **dot**, not a colon:

```lua
local text = net.get("https://example.com/")   -- right
local text = net:get("https://example.com/")   -- wrong: passes `net` as the URL
```

Only the functions documented here can be reached on them.

## Values crossing over

**Into Lua**, De-Algo hands tables, strings, numbers, booleans and `nil`. Lists are ordinary Lua lists,
walkable with `ipairs`.

**Back from Lua**, a table whose keys are exactly `1..n` becomes a list; any other table becomes a
mapping with string keys. Return plain data. Functions are only meaningful where a hook expects one.

## Errors

An error inside a hook is caught. The hook is treated as having no opinion: a condition lets the item
through, an ordering places nothing, `recognise` answers nothing, and the error goes to De-Algo's log.
A failing plugin never stops a run.

Use `pcall` to recover from your own errors.

**Related:** [Permissions](Permissions.md) · [Plugin Files](Plugin%20Files.md)
