# Plugin Files

## Layout

```
<id>/
├── plugin.lua      ← the entry file: runs first, and ends with return { … }
├── parse.lua       ← optional: more code, loaded with require("parse")
├── lib/
│   └── dates.lua   ← require("lib.dates")
├── README.md       ← optional, kept beside it
└── LICENSE         ← optional
```

- **The folder name is the plugin's id.** Use `a-z`, `0-9`, `-` and `_`. An `id` field in the file is
  ignored.
- **`plugin.lua` is the entry file.** It runs first and its `return { … }` is the plugin. Other files
  are not run unless something requires them.
- A loose `<id>.lua` still loads, and is moved into `<id>/plugin.lua` the next time Pamphlets starts.

## Splitting a plugin across files

```lua
-- parse.lua
local M = {}
function M.handle(reference) return string.match(reference, "^@([%w_]+)$") end
return M
```

```lua
-- plugin.lua
local parse = require("parse")
local dates = require("lib.dates")   -- dots are folders: lib/dates.lua
```

- **Only `.lua` files in the plugin's own folder**, named with letters, digits, `_` and dots. Nothing
  outside the folder, no `..`, no slashes, and not `plugin.lua` itself.
- **A module runs once.** Every `require` of the same name gets what its first run returned (or
  `true` if it returned nothing).
- **Modules share the plugin's world**: the same globals and the same capabilities (`settings`,
  `pamphlets`, and whatever was granted), under the same memory and time limits.
- A module that requires itself, directly or in a loop, is an error. So is a missing file, which names
  the file it looked for.
- Up to 64 modules, each up to 256 KiB.
- A plugin uploaded as a single `.lua` file has no folder, so it has nothing to require. Fetch it from
  a repository instead ([Distributing](Distributing.md)), which keeps every `.lua` file beside
  `plugin.lua`.

## Where plugins are read from

| Folder | Holds |
| --- | --- |
| `pamphlets/plugins/builtin/<id>/` | Shipped plugins, inside the image. |
| `<PAMPHLETS_DATA_DIR>/plugins/<id>/` | Plugins the admin added (`/data/plugins` in Docker). |

Both are read in name order, shipped first. A plugin in the data folder with the same id as a shipped
one **replaces** it. Plugins load on start, and again whenever one is added, removed, switched off or
has its permissions changed.

## The returned table

`plugin.lua` must end with `return { … }`. These keys are read; anything else is ignored.

| Key | Type | Required | Meaning |
| --- | --- | --- | --- |
| `api` | number | **yes** | The plugin API version. Must be `1`. |
| `name` | string | no | Shown on the Plugins page and in the palette. Defaults to the id. |
| `version` | string | no | Shown on the Plugins page. |
| `permissions` | list | no | What it asks to be allowed. See [Permissions](Permissions.md). |
| `sources` | list | no | Kinds of source. See [Sources](Sources.md). |
| `augmentations` | list | no | Conditions and orderings. See [Augmentations](Augmentations.md). `nodes` is accepted as an old name. |
| `publisher` | table | no | Writing back to the service. See [Publishing](Publishing.md). |

A plugin may offer sources only, augmentations only, or both.

## Names

`kind` values — of sources and of augmentations — use `a-z`, `0-9`, `-` and `_`. Keep source kinds to
12 characters or fewer: that is the width of the column they are stored in.

An augmentation is referred to as `<plugin id>:<kind>`, e.g. `hackernews:no-ask-hn`. Renaming either
part orphans the pieces people already placed.

## Two plugins, one source kind

A source kind belongs to one plugin. The second plugin to claim it fails to load with
*“kind” is already provided by …*. Switching the first one off releases the kind.

## When it does not load

The plugin's row on **Admin → Plugins** says why, and the rest of Pamphlets carries on. Common reasons:

| Message | Cause |
| --- | --- |
| *is written for plugin API none, and this is 1* | `api = 1` is missing. |
| *did not end with `return { … }`* | The file does not return a table. |
| *3: attempt to call a nil value (global 'name')* | A Lua error while loading, with its line number. |
| *“x” needs a `recognise` function* | A source without `recognise`. |
| *augmentation “x” goes under a filter, so it needs a `keep` function* | See [Augmentations](Augmentations.md). |
| *permission “x” needs a `why`* | Every permission needs a reason. |
| *hackernews ran too long and was stopped* | It hit the instruction limit while loading. See [The Sandbox](The%20Sandbox.md). |

**Related:** [The Sandbox](The%20Sandbox.md) · [Distributing](Distributing.md)
