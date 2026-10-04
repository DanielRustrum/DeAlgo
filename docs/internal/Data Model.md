# Data Model

All tables are in `dealgo/models/`. Times are stored as **naive UTC**. Names are historical:
a `Channel` is any source, a `Playlist` is any feed, a `Video` is any item.

```
User ─< LoginSession

  owner_pk on every table below (NULL = the implicit owner)

Settings (one per owner)        OAuthToken (per owner per plugin)   PluginUserSetting (per owner)   UserTheme (one per owner)

Channel ─< Video ─< Placement >─ Playlist
   │ ╲                              │
   │  channel_playlists (derived)───┘
   │
GraphNode ─< GraphEdge (source_pk → target_pk)
   │ channel_pk / playlist_pk / attached_to (piece → host)
   │
RepositoryItem >─ Video

SyncRun ─< RunEvent           PluginState, PluginAppSetting, AllowanceUsage (install-wide, no owner)
```

## Tables

| Table | One row is | Key columns |
| --- | --- | --- |
| `user` | An account | `username`, `password_hash` (scrypt), `is_admin`, `enabled` |
| `login_session` | A signed-in browser | `token_hash` (SHA-256 of the cookie), `expires_at` |
| `settings` | One owner's settings | `initial_backfill`, `post_seconds`, notice flags |
| `oauth_token` | One owner's sign-in to one plugin's service | `provider` (plugin id), `access_token`, `refresh_token`, `expires_at`, `refresh_error`, `account_title` |
| `channel` | A source | `channel_id` (the key a plugin resolved), `source_kind`, `source_url`, `mirror_url`, `left_out` (JSON: the plugin's `takes` it leaves out), legacy filter columns, `last_checked_at`, `enabled` |
| `playlist` | A feed | `playlist_id` (YouTube id, or `generic:…` for De-Algo feeds), `max_items`, `max_per_run`, `view_order`, `view_show` |
| `video` | An item | `video_id`, `kind` (`video`/`post`/`link`), `hint` (from `refine`), `status` (`pending`/`added`/`skipped`/`ignored`/`failed`), `tags`, `view_seconds`, `view_locked`, `watched_at` |
| `placement` | An item in a feed | `playlist_item_id` (NULL = owed), `added_at`, `removed_at`, `expires_at`, `attempts`, `error` |
| `graph_node` | A box or piece on the canvas | `kind`, `x`/`y`, `enabled`, `channel_pk`/`playlist_pk`, `attached_to`, per-kind columns (a group: `width`/`height`, `locked`) |
| `graph_edge` | A wire | `source_pk` → `target_pk` |
| `repository_item` | An item waiting in a named repository | `name` (normalised), `video_pk`, `deposited_by` |
| `allowance_usage` | Units spent against one plugin's service on its day (install-wide) | `provider`, `day`, `units`, `exhausted_at` |
| `plugin_app_setting` | A plugin's setting for everyone | `key` (`<plugin>:<name>`), `value` |
| `plugin_user_setting` | A plugin's setting for one owner | `key`, `value` |
| `user_theme` | One owner's theme, as the JSON an exported theme file holds | `slot` (always `current`), `data` |
| `user_image` | One owner's theme picture, as cleaned (`services/theming/images.py`) | `slot` (`background`, `edge-left`, `edge-right`, `heading`, the fonts `font-body` and `font-display`, and `avatar`, the account picture), `media_type`, `data` |
| `sync_run` | One run | counts, `trigger`, `forced`, `ok`, `quota_spent` |
| `run_event` | One line of a run's log | `seq`, `level`, `stage`, `about`, `message` |
| `plugin_state` | Admin decisions about a plugin | `plugin_id`, `enabled`, `granted` (JSON), `origin`, `origin_ref`, `fetched_at` |

## Item lifecycle (`video.status`)

```
          discovered
              │ beyond backfill ──▶ ignored  (reason "predates the backfill window")
              ▼
           pending ──every route refuses──▶ skipped  (reason = first refusal)
              │
   placed in ≥1 feed or deposited ──▶ added
              │
   3 failed inserts ──▶ failed
```

- A `pending` item with **no route** stays `pending`; wiring it later picks it up.
- A `skipped` item refused only because it is not YouTube and the feed is a YouTube playlist is
  revived to `pending` each run once a De-Algo feed or repository can take it (`reconsider_routing`).
- *Reach back* revives `ignored` items (`_unignore`).
- Rows are never deleted by a run: the row is what stops an item being added twice.

## Placement states

| `playlist_item_id` | `removed_at` | Meaning |
| --- | --- | --- |
| set | NULL | In the feed |
| NULL | NULL | Owed: deferred by a cap or quota, filled next run |
| set | set | Was in the feed; withdrawn (watched, expired, pruned) |

## Graph node columns by kind

`graph_node` is one wide table: each kind uses a few columns, the rest stay NULL.

| Kind | Uses |
| --- | --- |
| `source` | `channel_pk`, `label` |
| `feed` | `playlist_pk` |
| `trigger` | `trigger_kind` (`pulse`/`schedule`), `every_minutes`, `cron`, `last_fired_at` |
| `filter`, `sort` | `label`; behaviour comes from pieces under them |
| `deposit`, `withdraw` | `repository`, `takes` |
| `decay`, `expire`, `tag` | `tagged`, `marks`, timing comes from pieces |
| `group` | `width`, `height` |
| condition pieces | `title_include`/`title_exclude`, `min_duration_sec`/`max_duration_sec`, `tagged`, `max_per_run`, `sort_by`/`sort_dir` |
| `timer` | `duration_minutes`, `last_fired_at` (sitting start) |
| `reset` | `cron` |
| `alive` | `alive_from`, `alive_to` |
| `rule` | `plugin_ref`, `plugin_settings` (JSON) |

All pieces use `attached_to`. See [The Graph](The%20Graph.md).

## `channel.playlists` is derived

The `channel_playlist` association is a *view* of the wires, recomputed by
`graph.refresh_membership` whenever wiring changes. The graph is the only writer. Older code (feed
page chips, backups) still reads it.
