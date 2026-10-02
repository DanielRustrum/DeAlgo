# Web Layer

`dealgo/web/` is the whole HTTP surface: one FastAPI app (`app.py`), a router per part of the app
(`routes/`), server-rendered Jinja2 pages, htmx for partial updates, and a JSON API for the canvas.

## Why server-rendered

The container ships with no build step, every page works in any browser, and state lives in one
place. JavaScript enhances; it does not own data. The canvas is the one rich client, and even it
redraws from the server's answer after every change.

## Request pipeline

```
request
  └─ require_account middleware        identity from cookie; public / admin rules (guard.py)
       └─ route                        owner = owner_of(request)
            └─ services                every query owned(…, owner)
                 └─ render(template)  or JSONResponse  or redirect(path, ok=…, err=…)
```

- **Default deny.** Only `guard.PUBLIC_EXACT` (`/login`, `/logout`, `/healthz`, `/offline`,
  `/sw.js`, `/manifest.webmanifest`, `/favicon.ico`) and `/static/` are public. `/admin…` needs the
  admin. Everything else needs a signed-in account.
- **htmx-aware refusals.** Signed out → `401` with `HX-Redirect: /login?next=…` for htmx, `303` for
  normal requests. Not admin → `403` text or a redirect with `err`.
- **Flash messages** travel as `?ok=` / `?err=` query parameters after a `303` (post/redirect/get).
- **Sync routes run in the thread pool**; long work (runs) goes to a daemon thread.

## Pages

| Path | Page | Template |
| --- | --- | --- |
| `/` | Redirects to `/feed` | — |
| `/feed`, `/feeds/{id}` | Feed list and one feed | `feed.html`, `feed_detail.html` |
| `/focus`, `/watch` | Focus mode | `focus.html` |
| `/channels` | Configuration (canvas, stats, sources) | `channels.html` |
| `/channels/{id}` | One source | `channel_detail.html` |
| `/videos` | Raw list (no nav link) | `videos.html` |
| `/settings` | Settings | `settings.html` |
| `/admin`, `/admin/plugins` | Admin | `admin.html`, `plugins.html` |
| `/tour`, `/login`, `/offline` | — | `tour.html`, `login.html`, `offline.html` |

Templates starting `_` are partials, re-rendered by htmx (`/partials/log`, `/partials/stats`,
`/partials/sync-status`, `/partials/feed`).

## htmx conventions

- `<body hx-boost="true">`: links and forms become partial swaps without page reloads.
- Out-of-band swaps update secondary regions (e.g. the toast flash).
- `HX-Trigger: dealgo:sync-finished` tells scripts a run ended.
- Non-boosted fallbacks always work: every form posts and redirects.

## The canvas API

All JSON, all owner-scoped. Every mutating call answers with the **whole** graph payload
(`graph_payload`, in `routes/canvas/payload.py`), and the client redraws from it.

| Method & path | Does |
| --- | --- |
| `GET /api/graph` | Nodes, wires, palette (incl. plugin augmentations), windows, run state |
| `POST /graph/nodes` | Add a box or piece |
| `POST /graph/nodes/{id}` | Edit a node's fields |
| `POST /graph/nodes/{id}/move`, `/resize` | Position and size |
| `POST /graph/nodes/{id}/attach` | Slot or unslot a piece |
| `POST /graph/connect`, `/graph/disconnect` | Wires |
| `POST /graph/nodes/{id}/delete` | Remove |
| `POST /graph/nodes/{id}/fire`, `/backfill` | Run a trigger / reach back |
| `GET /api/graph/run` | Live `RunProgress`, polled while a run is going |
| `GET /graph/nodes/{id}/test` | `try_it` — dry run |
| `GET /graph/nodes/{id}/filtered` | What a Filter held, and why |
| `GET /graph/nodes/{id}/export`, `POST /graph/groups` | Group export / import |

`GraphError` messages are returned as `{"error": …}` with status 400 and shown verbatim.

## Other APIs

`/api/status` (JSON summary), `/healthz` (container health check). FastAPI's own `/docs`, `/redoc`
and `/openapi.json` are enabled — see [Known Issues](Known%20Issues.md).

## Static assets

`/static` is mounted from `web/static`. URLs carry `?v=<newest mtime>` (`ASSET_VERSION`) so a deploy
busts browser caches. The service worker is served from `/sw.js` (root scope).

**Related:** [Frontend](Frontend.md) · [Security](Security.md) · [Multi-Tenancy](Multi-Tenancy.md)
