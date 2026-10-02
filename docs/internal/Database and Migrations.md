# Database and Migrations

## Engine and sessions — `dealgo/db/`

- URL from `DEALGO_DATABASE_URL`, default `sqlite:///<DATA_DIR>/dealgo.sqlite3`.
- SQLite: `check_same_thread=False` (scheduler and request threads share the engine), 30 s busy
  timeout, and on every connection `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON`.
- `session_scope()` commits on success, rolls back on error, always closes.
  `expire_on_commit=False`, so objects stay readable after commit.
- `get_settings(session, owner)` / `get_token(session, owner)` create-or-fetch the owner's row.

SQLite is the supported database. Postgres works through SQLAlchemy in principle, but some
`VARCHAR` lengths are too short for values the app writes — see [Known Issues](Known%20Issues.md).

## Migrations — no Alembic

`init_db()` runs on every start, and every step is **idempotent**: it checks the current shape and
does nothing if already done. Order matters:

| Step | Does |
| --- | --- |
| `create_all` | Creates missing tables (never alters existing ones) |
| `add_missing_columns` | `ALTER TABLE … ADD COLUMN` for each `_ADDED_COLUMNS` entry not present |
| `rebuild_video_uniqueness` | Rebuilds `video` to drop a global `UNIQUE(video_id)` |
| `scope_uniqueness_to_owners` | Per-owner unique indexes via `COALESCE(owner_pk, 0)` |
| `rename_local_feed_prefix` | `local:` feed ids → `generic:` |
| `migrate_single_playlist` | Pre-multi-feed installs: one playlist in settings → `playlist`/`placement` rows |
| `retire_tag_nodes` | Remove canvas boxes that stood for a tag |
| `wires_belong_to_boxes` | Channel↔feed links → `graph_edge` rows from boxes |
| `feed_windows_become_pieces` | Trigger-into-feed → Timer/Reset pieces under the feed |
| `plugin_boxes_become_pieces` | Plugin boxes → a Filter carrying a `rule` piece |
| `rules_become_pieces` | Fields on Filter/Sort boxes → condition pieces (`_RULES_AS_PIECES`, `_SWITCHES_AS_PLUGIN_RULES`) |
| `drop_removed_columns` | Drop `_DROPPED_COLUMNS` — **last**, because earlier steps read them |
| then | `ensure_admin`, `clear_expired` sessions, `repair_stored_pictures` |

### Adding a column

1. Add it to the model (nullable or with a default).
2. Append `("table", "column", "SQL TYPE [NOT NULL DEFAULT …]")` to `_ADDED_COLUMNS`.
3. If existing rows need values, write a data step and add it to `init_db` after the column step.
4. Add a test in `tests/test_migration*.py` that builds the old shape and runs `init_db`.

### Removing a column

Add it to `_DROPPED_COLUMNS`. Any data step that still reads it must run first.

### Rebuilding a table (SQLite)

SQLite cannot drop a constraint in place. `rebuild_video_uniqueness` shows the pattern:
`legacy_alter_table=ON` (so a rename does not rewrite other tables' foreign keys to the old name),
`foreign_keys=OFF`, copy, drop, rename — on the raw driver connection, since neither pragma works
inside a transaction.

## Why hand-rolled

One file, no migration history to replay, no tool in the image, and every step is plain Python that
can be tested against an old database. The cost is discipline: steps must stay idempotent and
ordered.

## Times

Stored naive UTC (`models.utcnow()`). Convert at the edges: `_aware()` in graph code, `to_naive_utc`
for parsed feed dates, the template helpers `_ago`/`until` for display.

**Related:** [Data Model](Data%20Model.md) · [Testing](Testing.md)
