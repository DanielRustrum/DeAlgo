# Publishing and Quota

How Pamphlets writes to YouTube without the app knowing YouTube, and how it avoids running out of
quota mid-run.

## Two kinds of feed

| Feed | `playlist_id` | Placement | Cost |
| --- | --- | --- | --- |
| Pamphlets feed | `generic:…` | A `Placement` row with a local item id | Nothing |
| YouTube playlist | YouTube's id | A real playlist item via the API | Quota units |

Without a connected Google account, YouTube feeds collect locally too, and fill on YouTube once
connected (owed placements).

## The chain of a write

```
sync._publish
  └─ Publisher (plugins/publisher/)          neutral verbs: insert_playlist_item, playlist_items, …
       └─ YouTube plugin's `publisher` table  builds {method, url, query, body, cost}; reads the answer
            └─ account.send (plugins/capabilities/account.py)
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

## Signing in — a plugin's `connect`

Nothing about Google is the host's. A plugin declares how its service signs people in
(`registry/connect.py`: endpoints, scopes, extra consent parameters, the hosts the token is for, which
of its app settings hold the OAuth client and API key, its allowance, a `refusal` reader). The host
runs the flow:

- `services/oauth.py` — the generic authorization-code flow, refresh and revoke, given a `Connect`.
- `services/connections.py` — the client credentials (the plugin's app settings, then
  `DEALGO_PLUGIN_<ID>_<NAME>`, then defaults), tokens per `(owner, provider)` in `oauth_token`,
  refreshing (`valid_access_token`, failures kept in `refresh_error`), `build_client` for the
  publishing plugin, and `disconnect`.
- `web/routes/connections.py` — `GET /connect/{id}` (to the consent page), `GET /oauth/callback`
  (one address for every plugin; the in-memory `state` says which), and
  `POST /connect/{id}/disconnect`. `connection_view` is the block under Settings.

The OAuth client is the admin's, set once per install on the plugin's card. Each account signs in for
itself. `capabilities/account.py` signs only for the plugin's own `connect.hosts`.

## The quota ledger — `services/quota.py`

Google does not expose remaining quota, so Pamphlets keeps its own.

- **Whose:** the plugin's `connect.allowance`. Every function defaults to the publishing plugin.
- **Day** = the date in the allowance's `timezone` (YouTube: `America/Los_Angeles`). One
  `allowance_usage` row per provider per day, for the **whole install**: the OAuth client is the
  admin's, so every account spends the same allowance.
- **Budget** and **reserve** = the allowance's `daily` and `reserve`, each a number or one of the
  plugin's app settings (YouTube: `daily_quota`, default 10,000; `quota_reserve`, held back from
  syncing for manual actions). A service with no allowance is counted but never held back.
- `spendable = remaining − reserve` (0 once exhausted). Syncing checks `can_afford(units)`
  against `spendable`; manual actions and details reads pass `use_reserve=True`.
- **Pessimistic:** every request is charged when sent, success or not.
- **Believe the service over arithmetic:** a refusal whose reason (read by the plugin's
  `connect.refusal`) is `allowance.exhausted` calls `mark_exhausted`, which stamps `exhausted_at` and
  raises `units` to the budget for the rest of the day. `PublishError.is_quota_error` compares with
  the same declared reason.

## Stopping cleanly

Before each insert the engine checks `can_afford(cost_of("add"))`. If not, or if YouTube refuses for
quota:

1. `defer` writes an owed `Placement` (no item id) for every target the item still needs.
2. The run stops filing, sets `stopped_on_quota`, and says when the quota resets.
3. The next run's `retry_deferred` finishes owed placements first.

Feeds added *after* an item was handled get no owed row, which is what stops a new playlist
back-filling years of history.

## Adopting what is already there

Each YouTube playlist is read once per run (`playlist_contents`). An item already in it is adopted
(its existing item id recorded) instead of inserted twice.

## Pruning

`prune` trims each feed to `max_items`, oldest first — by API calls for YouTube playlists, by
marking placements removed for Pamphlets feeds.

## Known limits

Quota is counted per account, but accounts sharing one Google project share one real allowance. See
[Known Issues](Known%20Issues.md).

**Related:** [The Sync Engine](The%20Sync%20Engine.md) · [Plugin Registry](Plugin%20Registry.md)
