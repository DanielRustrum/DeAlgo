# Design Decisions

The choices that shape the codebase. Each says what was chosen, why, and what it costs.

## One process, one database
**Chosen:** FastAPI + APScheduler + SQLite in one container.
**Why:** A self-hosted app for a household should be one thing to run and one file to back up.
**Cost:** Runs are serialised; scale stops at a few accounts and hundreds of sources.

## One job per module
**Chosen:** A module does one thing. A job with several parts is a folder with a module per part, and
an `__init__.py` that exports what the rest of the app uses. Helpers one module hands another are
public names; underscores stay inside a module.
**Why:** A file small enough to read in one sitting is a file someone will actually read. Callers
keep writing `graph.routes(...)` whether `graph` is one file or twenty.
**Cost:** More files; and a test must patch the module that *uses* a name, not the package.

## One way out to the network
**Chosen:** Every outgoing request starts with `outgoing.client()`.
**Why:** One user agent, timeout and redirect policy — and one place for a test to stand in for the
network.

## Server-rendered HTML with htmx
**Chosen:** Jinja2 pages, `hx-boost`, partials; TypeScript only where interaction demands it.
**Why:** Works in any browser, no client state to drift, no build step in the image.
**Cost:** The canvas is a large hand-written script.

## The server owns the canvas
**Chosen:** Every canvas change is a POST answered with the whole graph; the client redraws.
**Why:** What is drawn is always what the database accepted. Refusals need no client-side undo.
**Cost:** One round trip per action (dragging is the local exception).

## The graph is the routing table
**Chosen:** Routes are computed from boxes and wires on each run; `channel.playlists` is derived.
**Why:** One writer, so the canvas and the engine cannot disagree. A second box for a channel is a
genuinely separate path.
**Cost:** Older code reading `channel.playlists` sees only direct wires.

## Triggers are the only reason to poll
**Chosen:** A source with no trigger is never polled by the heartbeat.
**Why:** Everything that happens should be explainable from the canvas.
**Cost:** A new source does nothing until wired to a trigger — a common first-run surprise.

## Pieces instead of settings
**Chosen:** Filter, Sort, feed windows and timers are configured by slotting pieces under boxes.
**Why:** A box shows what it does without being opened; plugins add conditions the same way the host
does.
**Cost:** Several migrations to convert older box fields into pieces.

## Nearest wins
**Chosen:** Where several things could decide, the one nearest the feed has the last word (filters
on a path, pieces in a chain, sorts).
**Why:** One rule, used everywhere, that matches reading the canvas left to right.

## Every service is a plugin, except the floor
**Chosen:** YouTube, Reddit, Bluesky and Substack are Lua plugins. RSS and Newsletter are built in.
**Why:** Service knowledge (URL shapes, endpoints, prices) changes without notice and belongs outside
the core. RSS and Newsletter belong to no service.
**Cost:** A sandbox to maintain; YouTube publishing goes through a capability layer.

## Lua, in-process, with capabilities
**Chosen:** lupa, one runtime per plugin, attribute filter, per-call ceilings, absent-unless-granted
capabilities.
**Why:** Small, embeddable, easy to sandbox; no subprocess management; grants are explicit and
bounded.
**Cost:** A hostile plugin shares the process; the defences must hold. Install is admin-only.

## The host signs, the plugin speaks
**Chosen:** Plugins describe requests; `account.send` attaches the token and charges quota.
**Why:** A plugin never holds a credential, so it cannot leak one.

## Owner on every row; `NULL` is an owner
**Chosen:** `owner_pk` on every owned table, narrowed by one helper; sign-in off means owner `NULL`.
**Why:** One code path for single-user and multi-user; a missed filter is the easy thing not to write.

## Pessimistic quota
**Chosen:** Charge before knowing the outcome; trust Google's "exhausted" over the ledger.
**Why:** Stopping slightly early beats being refused halfway through a playlist.

## Restartable runs
**Chosen:** Every decision is committed as made; owed placements record unfinished work.
**Why:** A crash or a quota stop loses nothing and never duplicates.

## Hand-rolled, idempotent migrations
**Chosen:** `init_db()` checks shape and converts on every start; no Alembic.
**Why:** No tool in the image, no history to replay, every step testable against an old database.

## Backups carry no secrets
**Chosen:** Neither per-account nor instance files include passwords, tokens or keys.
**Why:** Files that travel get leaked; credentials are cheap to re-enter.

## Large scripts written as parts, shipped as one
**Chosen:** The canvas and Focus mode are folders of TypeScript parts, compiled together and joined
into one script each (`ops/join_scripts.py`).
**Why:** Readable parts for whoever edits them; one file for the browser, because htmx re-inserts a
page's scripts and does not promise to run several in order.
**Cost:** A join step in `make js`, which a test keeps honest.

## Committed build output
**Chosen:** `app.css` and `*.js` are committed; tests fail if they drift.
**Why:** The image and `pip install` need neither Node nor Sass.

## Writing style in code
**Chosen:** Comments and docstrings explain *why*, in plain sentences; names say *what*.
**Why:** The reasons are what get lost. The autodoc reference is built from these docstrings.
