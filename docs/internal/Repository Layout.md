# Repository Layout

One rule shapes the tree: **a module does one job.** A job with several parts is a folder, with a
module per part and an `__init__.py` that exports what the rest of the app uses — so
`from pamphlets.services import graph` and `graph.routes(...)` read the same whether `graph` is one file
or twenty.

Every module opens with a docstring saying what it is for; the table below is those first lines.
The [API reference](autodoc/README.md) has the rest.

## Python — `pamphlets/`

| Folder | What it is | Modules |
| --- | --- | --- |
| `pamphlets/` | Pamphlets — a YouTube feed that answers to you, not the algorithm. | `__main__`, `config`, `outgoing`, `scheduler`, `cli/`, `db/`, `models/`, `plugins/`, `services/`, `sources/`, `web/` |
| `pamphlets/cli/` | The command line's commands, one module per subject. | `backups`, `logs`, `parser`, `serving`, `sources`, `status`, `syncing`, `watching` |
| `pamphlets/db/` | The database: engine, sessions, and bringing the schema up to date. | `engine`, `rows`, `startup`, `migrations/` |
| `pamphlets/db/migrations/` | Every change to the schema since the first release. | `columns`, `feeds`, `pieces`, `uniqueness`, `wires` |
| `pamphlets/models/` | Database schema, one table per module. | `account`, `base`, `canvas`, `feed`, `item`, `oauth`, `placement`, `plugin`, `quota`, `repository`, `run`, `settings`, `source`, `times` |
| `pamphlets/plugins/` | Plugins: Lua files that teach Pamphlets new sources and conditions. | `permissions`, `capabilities/`, `fetching/`, `publisher/`, `registry/`, `runtime/` |
| `pamphlets/plugins/capabilities/` | What a plugin is handed: one object per permission it was granted. | `account`, `clock`, `grant`, `log`, `net`, `owner`, `site`, `site_queries` |
| `pamphlets/plugins/fetching/` | Taking a plugin from a git repository. | `addresses`, `archive`, `download` |
| `pamphlets/plugins/publisher/` | Writing back to the service a feed came from, without knowing which it is. | `answers`, `client`, `reading` |
| `pamphlets/plugins/registry/` | What plugins there are, what each one offers, and what went wrong. | `current`, `decisions`, `manifest`, `offers`, `plugin`, `reading`, `storage` |
| `pamphlets/plugins/runtime/` | Running a plugin's Lua, and keeping it where it is put. | `errors`, `guard`, `sandbox`, `values` |
| `pamphlets/services/` | The domain: the canvas, the sync engine, accounts, quota and backups. | `auth`, `filters`, `oauth`, `ordering`, `quota`, `runlog`, `scope`, `watched`, `accounts/`, `backup/`, `channels/`, `graph/`, `migration/`, `playlists/`, `sync/` |
| `pamphlets/services/accounts/` | Who may sign in, and how that is proved. | `admin`, `errors`, `passwords`, `sessions`, `users` |
| `pamphlets/services/backup/` | Exporting everything Pamphlets knows as portable JSON. | `export`, `restore` |
| `pamphlets/services/channels/` | Adding and editing the sources this account watches. | `adding`, `listing`, `switches` |
| `pamphlets/services/graph/` | The Configuration canvas: what is wired to what. | `adding`, `canvas`, `conditions`, `cron`, `editing`, `errors`, `groups`, `names`, `pieces`, `reading`, `report`, `routes`, `stamps`, `trial`, `triggers`, `units`, `vocabulary`, `windows`, `wiring`, `words` |
| `pamphlets/services/migration/` | The whole instance, encrypted, for moving it to another machine. | `export`, `restore`, `sealing` |
| `pamphlets/services/playlists/` | Managing the set of playlists Pamphlets keeps filled. | `creating`, `editing`, `listing`, `membership` |
| `pamphlets/services/sync/` | The sync engine: poll feeds, filter, and push new uploads into the playlist. | `deciding`, `details`, `expiry`, `filing`, `lock`, `ordering`, `owed`, `pictures`, `placements`, `placing`, `polling`, `posts`, `progress`, `pruning`, `reasons`, `repositories`, `result`, `run`, `stamps`, `withdrawing` |
| `pamphlets/sources/` | Where things come from. | `embedded`, `items`, `newsletter`, `patience`, `kinds/`, `syndication/` |
| `pamphlets/sources/kinds/` | What a reference turns out to be, asked of the plugins that know. | `addresses`, `resolving`, `vocabulary` |
| `pamphlets/sources/syndication/` | Reading a feed, whichever of the two shapes it is written in. | `atom`, `entries`, `feed`, `pictures`, `rss`, `text` |
| `pamphlets/web/` | The web app: one FastAPI app, its server-rendered pages, and the scripts and styles they load. | `app`, `contexts`, `guard`, `responses`, `scripts`, `styles`, `templates`, `routes/` |
| `pamphlets/web/routes/` | Every page and endpoint, one module per part of the app. | `activity`, `admin`, `configuration`, `feed`, `feeds`, `focus`, `google`, `home`, `plugins`, `settings`, `shell`, `signing_in`, `sources`, `videos`, `canvas/` |
| `pamphlets/web/routes/canvas/` | The canvas's API. | `editing`, `facts`, `groups`, `notes`, `payload`, `running`, `saving`, `trying` |

## Everything else

```
pamphlets/web/templates/      Jinja2 pages; files starting _ are partials
pamphlets/web/styles/         Stylesheet sources for Tailwind; tokens.css is the theme, graph/ the canvas
pamphlets/web/ts/             Browser scripts; graph/ and focus/ are scripts written as parts
pamphlets/web/static/         Compiled app.css and *.js (committed), fonts, icons, htmx
pamphlets/plugins/builtin/    Shipped plugins: youtube, reddit, bluesky, substack, shape
ops/                       DevOps scripts: build CSS, join scripts, docs TOC, publish the wiki and releases
tests/                     pytest suite, fakes.py, and Node harnesses for the scripts
docs/wiki/                 User wiki (Nodes/ and Creating A Plugin/ inside)
docs/internal/             These pages, and autodoc/ for the generated reference
Makefile                   Every task: make help
tsconfig*.json             Page scripts, the service worker, and scripts written as parts
Dockerfile, *compose*.yml  The image and how to run it
.gitea/workflows/          CI: test then attach the image to a tag's release; publish the wiki
```

## Generated files

| Committed (so the image needs no compiler) | Not committed |
| --- | --- |
| `web/static/app.css` (`make css`), `web/static/*.js` (`make js`) — tests fail if they drift | `build/` (scripts compiled before joining), `docs/internal/autodoc/{python,browser,service-worker}/` (`make docs`) |
