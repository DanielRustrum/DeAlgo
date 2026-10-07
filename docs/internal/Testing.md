# Testing

```bash
make test          # .venv/bin/python -m pytest   (~1,340 tests)
make typecheck     # mypy --strict, tsc --noEmit (pages, worker, scripts written as parts)
```

CI runs both on every push before building the image.

## Fixtures — `tests/conftest.py`

| Fixture | Gives |
| --- | --- |
| `db` | A fresh SQLite file per test, wired into `pamphlets.db`, `init_db()` already run |
| `fresh_plugins` (autouse) | `registry.forget()` around each test, so a registry built against one database never answers for another |
| no-posts guard (autouse) | Stubs `Registry.posts` to `[]` so no test scrapes a real page; opt out with `@pytest.mark.reads_pages` |
| `world` | A channel wired to a playlist, `syndication.fetch` serving `state["entries"]`, `FakeYouTube` as the publisher (patched in `sync.run.build_client`), quota metered |

`PAMPHLETS_DATA_DIR` is set to `/tmp/pamphlets-tests` and Google variables are cleared **before**
`pamphlets.config` is imported.

## Fakes — `tests/fakes.py`

- `FakeYouTube` — a `Publisher` stand-in holding playlists in memory, recording inserts and
  deletes, and charging quota through `bind_meter` so budgets bite.
- `entry(...)` — build a feed entry.
- `wire(session, channel, playlist)` / `unwire(...)` — draw or remove a canvas wire.
- `use_config(monkeypatch, config)` — run under another configuration (sign-in on, another
  database) in every module that reads `CONFIG`, rather than in a hand-picked few.

No test talks to YouTube or the network: feeds are served by monkeypatching `syndication.fetch`,
the publisher by `FakeYouTube`, and anything else by patching `outgoing.client`, the one place
every outgoing request starts.

## Patch where it is looked up

A package's `__init__` re-exports names for callers; a module inside it imports them directly. So
patch the module that **uses** a name, not the package: `sync.polling._poll`, `sync.run.build_client`,
`registry.storage.folder`, `playlists.editing.build_client`. Patching the package attribute changes
what outside callers see and nothing inside.

## Test files by area

| Area | Files |
| --- | --- |
| Sync engine | `test_sync`, `test_backfill`, `test_pull_interval`, `test_posts`, `test_generic_feeds`, `test_shorts`, `test_watched`, `test_repository` |
| Graph | `test_graph` (incl. the Node harness), `test_ordering`, `test_filters` |
| Sources | `test_sources`, `test_feeds`, `test_newsletter`, `test_patience` |
| Plugins | `test_plugins`, `test_plugin_api`, `test_plugin_nodes`, `test_plugin_account`, `test_plugin_fetch`, `test_plugin_page`, `test_permissions`, `test_youtube_plugin` |
| Accounts | `test_accounts`, `test_tenancy` |
| Data | `test_backup`, `test_migration`, `test_migration_backup`, `test_migration_conditions`, `test_quota`, `test_runlog` |
| Web | `test_web`, `test_feed`, `test_focus`, `test_operations`, `test_pwa`, `test_toast` |
| Build guards | `test_scripts`, `test_styles`, and the packaging test in `test_plugins` |

## Browser logic without a browser

`tests/graph_harness.js`, `toast_harness.js` and `sw_harness.js` load the **compiled** script into a
Node `vm` context with a stub DOM, call its functions, and print JSON. Python tests run them with
`node` and assert on the output. Skipped where Node is absent.

## Guard tests worth knowing

| Test | Stops |
| --- | --- |
| `test_scripts.py` | Committed JS drifting from TS; top-level state; IIFEs; `!` assertions; selectors for classes the CSS lacks |
| `test_styles.py` | Committed CSS drifting from SCSS |
| `test_every_file_the_app_reads_from_its_own_package_is_shipped` | `package-data` globs missing files the app opens (it once shipped no plugins) |
| `test_tenancy.py` | One account reading another's rows |

## Writing a test

- Use the `db` fixture and real services; fake only the edges (publisher, HTTP).
- For a migration, build the **old** shape with raw SQL, run `init_db()`, assert the new shape.
- For a plugin, write it to `tmp_path/<id>/plugin.lua` and `registry.read(tmp_path, granted=…)`.
- Prove a new test fails without the fix before relying on it.
