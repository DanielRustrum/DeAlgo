# Known Issues

What is wrong or missing as of 2026-10-02, most serious first. Each says where, what happens, and
the likely fix.

## Account separation

These break the rule that accounts are private. They come first because the instance is shared.

### 1. Some routes act on another account's rows by id
`web/routes/feeds.py`, `videos.py`, `sources.py`, `focus.py` and `feed.py` look rows up with
`session.get(Model, id)` and never check the owner. A signed-in member who sends another account's
id can rename, re-cap, unlink or delete its feeds, change which sources fill them, stop watching
its sources, and requeue, ignore or mark its items (15 places: `grep -n "session.get(" dealgo/web`).
The canvas routes are scoped and tested; these older ones are not.
**Fix:** look rows up with `owned(...)` (a small `owned_get(session, Model, id, owner)` helper), and
add a tenancy test per route that tries another account's id.

### 2. Google disconnect, connect and quota use the implicit owner
- `oauth_disconnect` → `auth.disconnect()` takes no owner: a member's *Disconnect* revokes and
  deletes the implicit owner's Google grant, not their own.
- `oauth_start` and `oauth_callback` read the implicit owner's client id and secret, and the
  callback names the connected account using the implicit owner's token.
- Removing watched items and renaming a YouTube playlist check and mark the implicit owner's
  quota (`services/watched.py`, `services/playlists/editing.py`).
- `sync.placements.still_queued` counts waiting items across every account (only in a message).
**Fix:** pass `owner` through each call; add tenancy tests.

### 3. The YouTube playlist cache is shared between accounts
`web/contexts.py` caches the connected account's YouTube playlists in one module-level slot for two
minutes. Within that time another account's Settings and feed forms show the first account's
playlists.
**Fix:** key the cache by owner.

### 4. Restoring a per-account backup writes the implicit owner's settings

`services/backup/` — `build_export` and `restore` call `get_settings(session)` with no owner. A
member's export carries the **implicit owner's** settings, and a member's restore **overwrites** them
(`auto_sync`, `poll_interval_minutes` — the instance heartbeat — quota numbers, and, from older files,
Google client id/secret/API key). Breaks account separation.
**Fix:** pass `owner` to `get_settings` in both; stop restoring instance-wide fields from a
per-account file; add a tenancy test.

## Correctness and data

### 5. Per-account backups predate the canvas
`services/backup/` exports no nodes, wires, pieces, triggers or positions, and no `source_kind`,
`source_url` or `mirror_url`. A restored non-YouTube source comes back as YouTube and cannot be read.
Instance migration reuses the same `setup`, so it has the same gaps.
**Fix:** bump `FORMAT_VERSION`; export the graph by service ids and names, as `export_group` does.

### 6. New sources stay paused after wiring
Sources added on the canvas start disabled; only the feed page's chips call `follow_feed_links` to
enable them. The panel hint says it "stays paused until it is wired", which is not what happens.
**Fix:** enable on first wire into a path, or correct the hint and surface the switch.

### 7. Group export loses source kind
`export_group` / `import_group` carry channel ids but not `source_kind`/`source_url`; non-YouTube
sources import as YouTube.

### 8. Column lengths too short outside SQLite
`graph_node.kind` is `VARCHAR(8)` but kinds such as `shorter-than` are 12 characters;
`channel.source_kind` is `VARCHAR(12)`, and plugin kinds may be longer. SQLite ignores lengths;
Postgres would reject the writes.

## Behaviour that surprises

### 9. Triggers only fire on the heartbeat
Due-ness is checked every `poll_interval_minutes` (30). A 5-minute pulse fires every 30 minutes.
The heartbeat is no longer editable in the UI.

### 10. Sort only orders the batch
A Sort box orders insertion within a run. The Feed page and Focus mode order by publish date, so the
sort is invisible there for De-Algo feeds.

### 11. Focus mode ignores reading windows; Decay ignores videos
Focus does not consult Timer/Reset/Alive. Decay timers apply only to non-video items.
`Settings.post_seconds` is effectively unused.

### 12. No UI for fill order
`priority` on feeds and sources decides who fills first under quota pressure, with no way to change it.

### 13. CLI acts on the implicit owner
`dealgo add/export/channels/watched/remove-watched` (and `make backup`) operate on unowned rows,
which are empty once sign-in is on. Only `sync` and `serve` are useful there.

### 14. The tour is stale
It mentions *New feed*, *Track content*, the Raw tab and fill order.

### 15. Two "Newsletter" boxes
The Substack plugin's box is labelled Newsletter, as is the built-in Newsletter box.

## Security hardening

### 16. FastAPI docs are public to members
`/docs`, `/redoc` and `/openapi.json` are reachable by any signed-in account.
**Fix:** `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`.

### 17. Forwarded headers trusted from anywhere
`uvicorn.run(proxy_headers=True, forwarded_allow_ips="*")`. Exposed without a proxy, a client can
spoof its scheme and address (affecting the `Secure` cookie flag).
**Fix:** a `DEALGO_TRUSTED_PROXIES` variable defaulting to `127.0.0.1`.

### 18. No login rate limiting
Passwords are scrypt-hashed, but attempts are not throttled or locked out.

### 19. No security headers; CSRF relies on SameSite
No CSP, `X-Frame-Options` or `X-Content-Type-Options`. No CSRF tokens; `SameSite=Lax` cookies are
the only defence for POSTs.

### 20. Google tokens and client secrets stored in plaintext
In `oauth_token` and `settings`. The data volume must be protected.

## Plugins

### 21. A plugin is one file
The loader runs only `plugin.lua`, and the sandbox has no `require`, so a plugin cannot be split into
modules: the shipped YouTube plugin is 683 lines in one file.
**Fix:** a sandboxed `require` that loads only text files from the plugin's own folder, into the
same environment and under the same ceilings.

### 22. Account capability is Google-only, and there is one publisher
`account.send` signs only Google API hosts; only one `playlistable` plugin can publish.

### 23. Shared Google project quota
Quota is counted per account, but accounts using the same Google project share Google's real limit.

### 24. Abandoned fetches are not swept
A fetched plugin left unconfirmed stays in `plugins/.staged/` until the next fetch of the same id.

## Housekeeping

### 25. Stray hand-uploaded plugin on the live instance
`/data/plugins/plugin/plugin.lua` (id `plugin`) duplicates the shipped YouTube plugin and shows
"“youtube” is already provided by YouTube". Remove it from Admin → Plugins.
