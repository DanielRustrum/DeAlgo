# Repository Layout

```
dealgo/
  __main__.py           CLI: serve, sync, add, export, watched, remove-watched, channels, status
  config.py             Environment → CONFIG (frozen dataclass)
  db.py                 Engine, sessions, init_db() and every migration
  models.py             All tables
  scheduler.py          APScheduler heartbeat
  services/
    graph.py            The canvas: nodes, wires, pieces, routes, windows, groups, Test
    sync.py             The sync engine
    accounts.py         Users, passwords, login sessions
    auth.py, oauth.py   Google credentials and the OAuth flow
    scope.py            owned()/belongs_to(): per-account query narrowing
    channels.py         Adding and editing sources
    playlists.py        Adding and editing feeds
    filters.py          Pure accept/reject rules
    watched.py          Watched state and removal
    quota.py            The YouTube quota ledger
    runlog.py           Per-run event log
    backup.py           Per-account JSON backup
    migration.py        Encrypted whole-instance export
    ordering.py         Dense priority ordering
  sources/
    kinds.py            Reference → Resolved (asks plugins; RSS and Newsletter built in)
    syndication.py      RSS/Atom parser
    newsletter.py       Feed discovery from a site
    embedded.py         JSON embedded in pages
    items.py            Entry/Batch: one item, any source
    patience.py         Per-host back-off
  plugins/
    runtime.py          Lua sandbox (lupa)
    registry.py         Load, judge, grant, stage, keep plugins
    permissions.py      The permission vocabulary and capability objects
    site.py             The `dealgo` object plugins receive
    account.py          Signed requests without exposing the token
    publisher.py        Playlist operations through a plugin
    fetching.py         Plugins from git host archives
    builtin/<id>/       Shipped plugins: youtube, reddit, bluesky, substack, shape
  web/
    app.py              Every route
    guard.py            Public/admin path rules
    styles.py           SCSS → app.css
    templates/          Jinja2
    scss/               Stylesheet sources
    ts/                 TypeScript sources
    static/             Compiled app.css and *.js (committed), icons, htmx
tests/                  pytest suite plus Node harnesses
docs/                   wiki/, internal/
Dockerfile, docker-compose.yml, compose.cluster.yml, Makefile
.gitea/workflows/       CI: test then publish the image
```

## Generated files that are committed

`web/static/app.css` and `web/static/*.js` are build output, committed so the image needs no
compiler. Tests fail if they drift from their sources. See [Frontend](Frontend.md).

## Generated files that are not

`docs/internal/autodoc/{python,browser,service-worker}/` — produced by `make docs`.
