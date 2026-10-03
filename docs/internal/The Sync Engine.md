# The Sync Engine

`services/sync/`. One **run** is one pass for one account: poll what is due, route and place what
is pending, then tidy up. Every decision is written as it is made, so a crash costs at most the
items in flight and nothing is ever added twice.

## Entry points

| Call | Used by | Scope |
| --- | --- | --- |
| `run_for_everyone("scheduled")` | Scheduler heartbeat | Each owner with a channel, in turn |
| `run_sync("manual", force=True, owner=…)` | *Sync now* | One owner, every source |
| `run_sync("pulse", force=True, only=…, sources=…, withdrawals=…, fired_by=…)` | A trigger's ▶ button | The channels, source boxes and Withdraw boxes that trigger reaches |
| `run_sync("backfill", reach_back=N, …)` | Reach back | As above, re-reading the latest N items |
| `withdraw_now(boxes)` | A trigger wired only to Withdraw boxes | No run; pulls immediately |

`run_sync` takes the process-wide `playlist_lock` (non-blocking — a second run returns
"A sync is already running") and always calls `finish(token)` so the canvas stops watching.

`only` narrows **polling** by channel. `sources` narrows **filing** by source box — a channel drawn
twice is one poll but two boxes, and a trigger reaches one box. A scheduled run passes neither and
files through the whole graph.

## Phases of `run._run`

```
SyncRun row created ─▶ polling ─▶ sorting ─▶ filling ─▶ stamping/sweeping ─▶ withdrawing ─▶ done
```

### 1. Polling — `discover`

For each enabled channel (by `priority`, `id`):

1. Skip unless `only` includes it, and unless forced, unless `_channel_due` — some wired trigger's
   `When.due(last_checked_at, now)`. **No trigger, no poll.**
2. `_poll` → `_read_feed`: fetch `channel.feed_url`; on a refusal (`RateLimited` or 403/429/503)
   try `mirror_url`; if that fails too, raise the original refusal.
3. Each item passes through the source plugin's `refine` (id, `kind`, `hint`). Items with no
   plugin id get `item-` + SHA-1(`channel_id|guid`)[:24].
4. Known items are refreshed (`_freshen`: newest reading wins, never replaced by empty). New items
   become `Video` rows: `pending`, or `ignored` (*predates the backfill window*) if beyond the
   backfill — the first `initial_backfill` entries on a first check, or `backfill_days` if the
   channel sets it.
5. If the source's plugin has extras (`posts`), `discover_posts` collects them under the same
   backfill rules.
6. Errors are recorded on `channel.last_error` and the run log; the run continues.

`reach_back` treats the poll as a first check with backfill = N and revives that many `ignored`
items (`_unignore`).

### 2. Sorting — `fill_missing_details`

Channels added by bare id get avatar, handle and description from the publisher (50 per unit).

### 3. Filling — `filing.publish`, `placing.Placing`

`publish` reads as these steps; placing each item is a `Placing` object (`placing.py`) that carries
the run's counts, each YouTube playlist's contents (read once) and whether quota ran out.

1. `retry_deferred` (`owed.py`): finish owed placements (no item id, not removed, attempts left). Stops the run
   here if quota runs out again.
2. `reconsider_routing`: revive `skipped` items whose only refusal was "not a YouTube video" if a
   De-Algo feed or repository now reaches their channel.
3. Load `pending` items ordered by channel priority, then publish date.
4. Compute routes once; keep those in `sources` (if given) and whose feed is enabled.
5. Fetch video details for YouTube videos (duration, counts, live state) when affordable.
6. `reorder`: apply Sort boxes (see [Algorithms](Algorithms.md#batch-ordering)).
7. For each item, `Placing.file`:
   - No routes → stays `pending`.
   - `decide` per route (below). `attribute` marks which Filter box stopped it, for the canvas.
   - `apply_stamps` with every accepting route: tags, Decay seconds, Lock.
   - No route accepts → `skipped` with the first reason.
   - Deposit into each named repository once (`deposit`).
   - Posts → `place_locally` (no API).
   - Other items → each target feed, deduplicated, in feed `priority` order:
     - already placed → skip;
     - De-Algo feed, or no Google account → local placement (`generic:` id), subject to
       `max_per_run`;
     - YouTube playlist → adopt if already present in the playlist, else check quota, else insert.
       Quota stop → `defer` owed placements for every remaining target and stop the loop.
     (`_place`, `_place_here`, `_place_on_youtube`, `_owe`)
   - `stamp_expiry` on placements made down routes with Expire boxes.
   - Status (`_settle`): `added` if it landed anywhere; stays `pending` if only deferred;
     otherwise `attempts += 1`, `failed` after 3.
8. `prune`: trim each feed to `max_items` (oldest first), on YouTube or locally.

If no Google account is connected, YouTube feeds collect inside De-Algo. If quota is already spent,
filing still runs but YouTube writes are deferred.

### 4. Stamping and sweeping

- `stamp_what_is_already_here`: give existing placements under a newly wired Expire box their end.
- `sweep_expired`: withdraw placements whose `expires_at` has passed (from YouTube if needed).

### 5. Withdrawing — `withdraw_what_is_due`

Each Withdraw box whose trigger is due (or that was pressed) takes up to `takes` items, **oldest
first**, deletes them from the repository, and files them down `paths_from(box)` with the same
`decide`.

### 6. Done

Counts, `ok`, and `quota_spent` are written to `sync_run`; old run logs are pruned.

## `decide(video, route)`

In order, first refusal wins:

1. **Carrying** — the route's `tagged` condition, counting tags this route would add.
2. **Wrong kind** — a non-YouTube item into a YouTube playlist.
3. **Plugin conditions** — each `rule` in `route.checks`, inside `capabilities.acting_for(owner)`. `keep`
   returning false refuses with *held by <piece title>*. A plugin that is off or gone, or that
   errors, has no opinion.
4. **Built-in rules** on `route.effective()`: `filters.evaluate` (videos: shorts, live, duration,
   include/exclude words) or `filters.evaluate_post` (posts and links: words only).

## Observability

| What | Where | Lifetime |
| --- | --- | --- |
| `RunProgress` | Memory, `/api/graph/run` | The current run; drives canvas highlighting |
| `RunEvent` lines | `run_event` via `runlog.Pen` | Last 40 runs keep detail, ≤ 600 lines each |
| `SyncRun` counts | `sync_run` | Kept |
| Python logging | stdout | Container logs |

**Related:** [The Graph](The%20Graph.md) · [Triggers and Scheduling](Triggers%20and%20Scheduling.md) ·
[Publishing and Quota](Publishing%20and%20Quota.md)
