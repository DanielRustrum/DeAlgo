# Multi-Tenancy

One instance serves several accounts. Each account's sources, feeds, canvas, settings, Google grant,
quota and run log are its own. The admin manages accounts but cannot see their data.

## Two modes, one code path

| `DEALGO_ADMIN_USER` set? | Mode | Owner of every row |
| --- | --- | --- |
| No | Sign-in off | `NULL` — the *implicit owner* |
| Yes | Sign-in on | The signed-in user's `user.id` |

The same queries serve both: `owner_pk IS NULL` is just another owner. There is no separate
single-user path to drift.

## How a request gets its owner

1. `require_account` middleware (`web/app.py`) reads the `dealgo_session` cookie and resolves an
   `Identity` (`username`, `is_admin`, `user_pk`).
2. Every route calls `owner_of(request)` → `identity.user_pk`, or `None` when sign-in is off.
3. Services take `owner: OwnerId` and pass it to every query.

There is no route that takes an owner from the URL or form.

## Narrowing queries: `services/scope.py`

```python
owned(select(Channel), Channel, owner)   # WHERE owner_pk = :owner  (or IS NULL)
belongs_to(Video, owner)                 # the condition alone, for joins
stamp(row, owner)                        # set owner_pk on a new row
```

`belongs_to` exists because `owner_pk == None` is not `IS NULL` in SQL. The `Owned` union lists
every owned table explicitly, so adding a table forces a decision about ownership.

Tables **without** an owner: `user`, `login_session`, `placement` (reached through its video),
`plugin_state` (install-wide), and the `channel_playlist` association.

## Uniqueness is per owner

Two accounts can follow the same channel. `scope_uniqueness_to_owners` creates unique indexes on
`(COALESCE(owner_pk, 0), column)` for `channel.channel_id`, `playlist.playlist_id` and
`quota_usage.day` — `COALESCE` because SQL treats NULLs as distinct, so a plain
`UNIQUE(owner_pk, …)` would let the implicit owner hold duplicates. `video` had a global
`UNIQUE(video_id)` inside its `CREATE TABLE`, which SQLite cannot drop, so
`rebuild_video_uniqueness` rebuilds that table. See [Database and Migrations](Database%20and%20Migrations.md).

## Syncing

`run_for_everyone` (the heartbeat) finds every owner with a channel and runs `run_sync(owner=…)` for
each **in turn**. Sequential on purpose: one SQLite file, one playlist lock, and quota is per owner.

## Plugins and owners

Plugins are install-wide; data is not. The `dealgo` and `account` capabilities answer nothing
until the host enters `capabilities.acting_for(owner)`, which the sync engine does only around `keep`,
`rank`, `posts` and publisher calls. Outside it, `dealgo.sources()` is empty and changes are
refused. Enforced in one place (`plugins/capabilities/`) so no plugin function can forget it. See
[Plugin Registry](Plugin%20Registry.md).

## The admin

- Comes from `DEALGO_ADMIN_USER` / `DEALGO_ADMIN_PASSWORD`, reconciled on every start
  (`accounts.ensure_admin`). Changing the variable and restarting is the recovery path.
- Sees `/admin/*` (accounts, plugins, instance migration). `guard.needs_admin` gates it.
- Has their own canvas and feeds like anyone else, and no view into others'.

## Tests

`tests/test_tenancy.py` creates two accounts and asserts each route and service sees only its own
rows. Add a case there for any new owned table or route.
