# Architecture

Pamphlets is one Python process serving a server-rendered web app, running a background scheduler,
and storing everything in one SQL database. No queue, no cache server, no worker fleet.

```
                ┌──────────────────────── one process ───────────────────────┐
 browser ──────▶│ FastAPI app (web/app.py), routers (web/routes/)            │
  htmx, canvas  │   middleware: who is this? (web/guard.py, accounts/)       │
                │   routes ──▶ services/*  ──▶ SQLAlchemy ──▶ SQLite/Postgres│
                │                  │                                         │
                │ APScheduler ─────┤ heartbeat: run_for_everyone()          │
                │  (thread)        ▼                                         │
                │            sync engine (services/sync/)                    │
                │              │ routes from      │ polls via                │
                │              ▼                  ▼                          │
                │         services/graph/     sources/* ──▶ outgoing ──▶ web │
                │                                 │                          │
                │         plugins/registry ──▶ Lua sandbox (lupa)            │
                │              │ publisher/account ──▶ YouTube Data API      │
                └────────────────────────────────────────────────────────────┘
```

## Layers

| Layer | Package | Knows about |
| --- | --- | --- |
| Web | `dealgo/web` | HTTP, templates, who is signed in. Calls services. |
| Services | `dealgo/services` | The domain: graph, sync, accounts, quota, backups. |
| Sources | `dealgo/sources` | Reading feeds and pages. Nothing about accounts or feeds. |
| Plugins | `dealgo/plugins` | Running Lua and exposing what it declares. |
| Storage | `dealgo/models/`, `dealgo/db/` | Tables, sessions, migrations. |

Dependencies point downwards. `sources` never imports `services`; `plugins/runtime` knows nothing
about sources or graphs.

## Threads

- **Request threads.** FastAPI runs sync routes in its thread pool.
- **Scheduler thread.** APScheduler fires `run_for_everyone` every heartbeat
  (`Settings.poll_interval_minutes`, default 30). See [Triggers and Scheduling](Triggers%20and%20Scheduling.md).
- **Manual runs.** *Sync now* and trigger buttons start `run_sync` in a background thread.

One process-wide lock (`sync.playlist_lock`) serialises everything that writes to playlists. A second
run that cannot take it returns at once with "A sync is already running". SQLite runs in WAL mode so
readers do not block the writer.

## The life of an item

1. **Trigger.** The heartbeat (or a button) starts a run for one account.
2. **Poll.** Each source whose trigger says it is due is fetched. New entries become `Video` rows
   with status `pending`. See [The Sync Engine](The%20Sync%20Engine.md).
3. **Route.** The graph is walked from every source box to every feed or Deposit it reaches. See
   [The Graph](The%20Graph.md).
4. **Decide.** Each pending item is judged per route: channel defaults, Filter conditions,
   plugin conditions.
5. **Place.** Accepted items get a `Placement` per feed — a local id for Pamphlets feeds, or a real
   playlist item via the YouTube plugin. Deposits go to `RepositoryItem`.
6. **Stamp.** Decay, Expire and Tag boxes on the route leave their marks.
7. **Sweep.** Expired placements are withdrawn; due Withdraw boxes pull from repositories.
8. **Read.** The Feed page and Focus mode render placements, gated by the feed's reading window.

## Where state lives

| State | Where | Why |
| --- | --- | --- |
| Everything durable | Database | One place to back up |
| Plugins | `<DATA_DIR>/plugins/<id>/` and the package | The folder is the truth |
| Run progress (live) | Memory (`RunProgress`) | Changes many times a second, worthless after |
| Host rate-limit advice | Memory (`patience`) | Worthless after a restart |
| OAuth `state` tokens | Memory | A restart should break a half-done sign-in |
| Plugin registry | Memory, rebuilt on demand | Derived from folders and DB rows |
