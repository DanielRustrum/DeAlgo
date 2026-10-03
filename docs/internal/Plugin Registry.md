# Plugin Registry

`plugins/registry/` decides what plugins exist, what each offers, and what went wrong.
Beside it: `permissions.py` (the vocabulary), `capabilities/` (what a plugin is handed: `clock`,
`log`, `net`, `account`, the `dealgo` object in `site`, and `owner` for whose work is in hand),
`publisher/` (playlist operations) and `fetching/` (git archives).

## Where plugins come from

| Folder | Trust | Notes |
| --- | --- | --- |
| `dealgo/plugins/builtin/<id>/plugin.lua` | Shipped: granted what it asks for until the admin changes it | youtube, reddit, bluesky, substack, shape |
| `<DATA_DIR>/plugins/<id>/plugin.lua` | Granted only what the admin ticked | Uploads and fetches |

The id is the **folder name**, never anything the file says. Later folders win, so a data-folder
plugin with a shipped id replaces the shipped one (`plugin.replaces`). `settle()` moves legacy loose
`<id>.lua` files into folders on start.

## Lifecycle

```
current() ── first use ──▶ _everything()
                             settle(data folder)
                             _state(): paused ids, grants (plugin_state rows)
                             read(shipped, data, trusted=shipped)
reload()  ── upload, fetch, pause, grant change ──▶ _everything()
forget()  ── tests
```

The registry is held in memory and rebuilt on demand, never stored: the folder is the truth.

## Loading one plugin — two passes

1. **Judge** (`_judge`): load with a `dealgo` granted nothing. Check it returned a table,
   `api == 1`, id is `[a-z0-9_-]`. Parse `permissions`, `sources`, `augmentations` (and legacy
   `nodes`), `publisher`. Any problem becomes `plugin.trouble` — shown on the Plugins page — and
   the rest of the app carries on. A source's `colour` must be in `SOURCE_COLOURS`
   (`registry/plugin.py`); each name has a `--plugin-*` token and a `data-colour` rule in
   `web/styles/plugin-colours.css`, and a test keeps the three in step.
2. **Grant** (`_grant`): granted = stored grant ∩ what it asked for ∩ known permissions. If it asked
   for anything, load it **again** with those capabilities and re-read its declarations.

The first pass means a plugin's top-level code never runs with a capability while its manifest is
being read.

## Conflicts

After loading, each non-paused plugin claims its source kinds in name order. A second claimant loses
the kind and gets *“<kind>” is already provided by <plugin>*. A paused plugin claims nothing — the
way to hand a kind to a replacement.

## What the registry answers

| Method | Asked by | Calls in Lua |
| --- | --- | --- |
| `recognise(ref)` / `accept(kind, ref)` | `sources.resolve` | each kind's `recognise` |
| `refine(kind, item)` | sync polling | `refine` |
| `posts(kind, key)` / `has_extras` | sync polling | `posts` (≤ 200) |
| `keeps(ref, item, settings)` | `decide` | augmentation `keep` |
| `ranks(ref, item, settings)` | `reorder` | augmentation `rank` |
| `augmentations()` / `augmentation(ref)` | canvas palette, `piece_hosts` | — |
| `home`, `item_url`, `mirror` | UI links, mirrors | `home`, `item_url`, `mirror` |

Errors inside a hook are logged and treated as **no opinion**.

## Capabilities

Built per plugin per load by `capabilities.granted_to`; absent unless granted.

| Permission | Global | Ceiling |
| --- | --- | --- |
| `network` | `net` (`get`, `embedded`, `find`) | 4 requests/call, 2 MiB/response, header allow-list (`user-agent`, `accept`, `accept-language`, `referer`), honours `patience` |
| `clock` | `clock` | — |
| `log` | `log` | prefixed with the plugin name |
| `read` | `dealgo.sources/feeds` | owner-scoped |
| `manage` | `dealgo.pause/watch` | owner-scoped |
| `account` | `account.send` | Google API hosts only, 30 calls/call, cost 1–100 each, 4 MiB |
| *(always)* | `settings` (`app`, `user`) | The plugin's own values only; `user` for the owner in hand, else defaults |

## Acting for an owner

Plugins are install-wide; data is per account. `capabilities.acting_for(owner)` sets a **thread-local**
owner for the duration of a block. `dealgo` and `account` read it: outside a block they answer
nothing and refuse changes. The sync engine opens a block around `keep`, `rank`, `posts` and
publisher calls. Nested blocks restore the outer owner.

## Publishing through a plugin

`publisher.Publisher` holds the conversation shape (lookup, read playlist, add, remove, create,
rename, details). The plugin's `publisher` table builds each request and reads each answer;
`account.Account` signs it with the owner's token for that plugin's service, charges its allowance,
and refuses any host not in the plugin's own `connect.hosts`. The plugin never sees the token. Only a `playlistable` source kind's plugin is asked.
See [Publishing and Quota](Publishing%20and%20Quota.md).

## Installing

| Step | Upload (`POST /admin/plugins`) | Fetch (`POST /admin/plugins/fetch`) |
| --- | --- | --- |
| Receive | Plain `.lua` filename, ≤ 256 KiB, UTF-8 | `fetching.fetch(url, ref)` |
| Judge | `registry.judge`, nothing granted | same |
| Hold | In the form only | `registry.stage()` into `plugins/.staged/<id>` |
| Consent | Page lists permissions and reasons; admin ticks | same |
| Keep (`/confirm`) | Re-judge; `registry.keep(id, source)` | Re-judge; `take_staged(id)` (rename); `set_origin(url, ref)` |
| Then | `set_granted`, `reload()` | same |

Nothing is written to the live folder before consent. Granting never exceeds what the plugin asked
for, whatever the form says.

### `fetching/`

- HTTPS only. `archives(url, ref)` builds candidate URLs: GitHub →
  `codeload.github.com/<o>/<r>/tar.gz/<ref>`; others → `<host>/<o>/<r>/archive/<ref>.tar.gz`; a
  direct `.tar.gz` as given. No ref → `main` then `master`.
- Download ≤ 2 MiB. Unpack treating everything as hostile: ordinary files only (no links or
  devices), no absolute paths or `..`, ≤ 200 files, ≤ 8 MiB unpacked.
- Entry is the shallowest `plugin.lua`. Keep only `.lua .md .txt .json .toml` and
  `LICENSE LICENCE COPYING NOTICE` beside it, up to three folders deep.
- Id from the repository name, minus `dealgo-plugin-`/`dealgo-`/`plugin-`.
- Git is never run: a clone runs hooks and reads config; an archive is inert.

## State in the database

`plugin_state` per id: `enabled` (pause), `granted` (JSON list), `origin`, `origin_ref`,
`fetched_at`.

Plugin settings: a plugin declares `settings = { app = {…}, user = {…} }`, parsed by
`registry/settings.py` (`settings_in`, the `Setting` kinds text/number/toggle/choice/secret) onto
`Plugin.settings`. Values live in `plugin_app_setting` (no owner; the admin's, for everyone) and
`plugin_user_setting` (owned, adopted with the rest when sign-in is turned on), each keyed
`<plugin id>:<name>`, read and written by `services/plugin_settings.py`. That service caches what
it has read, because `keep` reads per item, and any save clears the cache. The forms are
`routes/plugin_settings.py`: `POST /settings/plugins/{id}` (the account's own) and
`POST /admin/plugins/{id}/settings` (admin, guarded by path). Secrets are never rendered back.
Removing a plugin calls `plugin_settings.forget`. Neither table is in backups or migration files. Removing a plugin deletes its folder (`discard`); pieces using it stay on canvases and
do nothing.

**Related:** [Plugin Runtime](Plugin%20Runtime.md) · [Security](Security.md) ·
[Creating A Plugin](../wiki/Creating%20A%20Plugin/GETTING%20STARTED.md)
