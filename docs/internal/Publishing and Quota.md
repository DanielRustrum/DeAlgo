# Publishing and Quota

How De-Algo writes to YouTube without the app knowing YouTube, and how it avoids running out of
quota mid-run.

## Two kinds of feed

| Feed | `playlist_id` | Placement | Cost |
| --- | --- | --- | --- |
| De-Algo feed | `generic:…` | A `Placement` row with a local item id | Nothing |
| YouTube playlist | YouTube's id | A real playlist item via the API | Quota units |

Without a connected Google account, YouTube feeds collect locally too, and fill on YouTube once
connected (owed placements).

## The chain of a write

```
sync._publish
  └─ Publisher (plugins/publisher.py)        neutral verbs: insert_playlist_item, playlist_items, …
       └─ YouTube plugin's `publisher` table  builds {method, url, query, body, cost}; reads the answer
            └─ account.send (plugins/account.py)
                 ├─ refuse unless host ∈ googleapis.com / www.googleapis.com / youtube.googleapis.com
                 ├─ attach Bearer <owner's access token>     (plugin never sees it)
                 ├─ quota.meter(owner)(cost)                  (charged whether or not it worked)
                 └─ httpx request, ≤ 4 MiB answer → Lua table
```

- `auth.build_client(owner)` returns a `Publisher` that is *writable* with a valid OAuth token and
  *readable* with a token or an API key. It refreshes expiring tokens first (`valid_access_token`).
- Only the plugin of a `playlistable` source kind is asked.
- Prices come from the plugin's `costs` table (`cost_of`): read 1, add 50, remove 50, create 50,
  rename 50, search 100.

## OAuth

`services/oauth.py`: authorization-code flow with scope `https://www.googleapis.com/auth/youtube`
(playlist writes need it). `state` tokens live in memory. The refresh token is stored per owner in
`oauth_token`; a failed refresh is kept in `refresh_error` and shown in Settings. Each account uses
its own Google client id/secret from Settings, falling back to the `DEALGO_CLIENT_ID`/
`DEALGO_CLIENT_SECRET` environment.

## The quota ledger — `services/quota.py`

Google does not expose remaining quota, so De-Algo keeps its own.

- **Day** = the date in `America/Los_Angeles`, when Google resets. One `quota_usage` row per owner
  per day.
- **Budget** = `Settings.daily_quota` (default 10,000). **Reserve** = `quota_reserve`, held back
  from syncing for manual actions.
- `spendable = remaining − reserve` (0 once exhausted). Syncing checks `can_afford(units)`
  against `spendable`; manual actions and details reads pass `use_reserve=True`.
- **Pessimistic:** every request is charged when sent, success or not.
- **Believe Google over arithmetic:** a quota error calls `mark_exhausted`, which stamps
  `exhausted_at` and raises `units` to the budget for the rest of the day.

## Stopping cleanly

Before each insert the engine checks `can_afford(cost_of("add"))`. If not, or if YouTube refuses for
quota:

1. `_defer` writes an owed `Placement` (no item id) for every target the item still needs.
2. The run stops filing, sets `stopped_on_quota`, and says when the quota resets.
3. The next run's `_retry_deferred` finishes owed placements first.

Feeds added *after* an item was handled get no owed row, which is what stops a new playlist
back-filling years of history.

## Adopting what is already there

Each YouTube playlist is read once per run (`playlist_contents`). An item already in it is adopted
(its existing item id recorded) instead of inserted twice.

## Pruning

`_prune` trims each feed to `max_items`, oldest first — by API calls for YouTube playlists, by
marking placements removed for De-Algo feeds.

## Known limits

Quota is counted per account, but accounts sharing one Google project share one real allowance. See
[Known Issues](Known%20Issues.md).

**Related:** [The Sync Engine](The%20Sync%20Engine.md) · [Plugin Registry](Plugin%20Registry.md)
