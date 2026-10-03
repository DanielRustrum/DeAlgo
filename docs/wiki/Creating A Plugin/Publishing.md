# Publishing

A plugin can teach De-Algo to write back to its service — for YouTube: look channels up, read video
details, and fill playlists. This is how YouTube-backed [feeds](../Nodes/Feeds.md) work.

The `publisher` table is consulted only for a plugin with a source kind marked `playlistable = true`.
Only one plugin publishes; today that is YouTube. Your functions build requests and read answers;
the actual signed calls go through [`account.send`](Account.md).

## The table

```lua
publisher = {
  costs = { read = 1, add = 50, remove = 50, create = 50, rename = 50, search = 100 },

  resolve  = function(reference) … end,
  describe = function(ids) … end,
  details  = function(ids) … end,
  playlists = function() … end,
  playlist = function(id) … end,
  create   = function(title, description, privacy) … end,
  rename   = function(id, title) … end,
  contents = function(id) … end,
  add      = function(playlist_id, video_id) … end,
  remove   = function(item_id) … end,
  address  = function(playlist_id) … end,
},
```

Any function may be left out; De-Algo then reports that the plugin cannot do that.

## Functions

Rows are tables. A function that returns one table instead of a list is read as a one-row list.

| Function | Called with | Returns |
| --- | --- | --- |
| `resolve` | what was typed, e.g. `@handle` | channel rows (first is used) |
| `describe` | a list of channel ids | channel rows |
| `details` | a list of video ids | detail rows |
| `whoami` | — | a list holding `{ title }`, the account's name |
| `address` | a playlist id | the `https://` address it opens at, for a feed's "Open on …" link. Called without an account. |
| `playlists` | — | playlist rows: the account's playlists |
| `playlist` | a playlist id | a list holding one playlist row |
| `create` | title, description, privacy (`"private"`, `"unlisted"`, `"public"`) | a list holding the new playlist row |
| `rename` | playlist id, new title | anything truthy on success |
| `contents` | a playlist id | item rows |
| `add` | playlist id, video id | a list holding `{ item_id }` |
| `remove` | an item id | anything truthy on success |

| Row | Fields |
| --- | --- |
| channel | `id`, `title`, `handle`, `thumbnail`, `description` |
| detail | `id`, `title`, `duration` (seconds), `live` (`"none"`, `"live"`, `"upcoming"`), `privacy`, `views`, `likes` |
| playlist | `id`, `title`, `count`, `privacy` |
| item | `item_id`, `video_id`, `position`, `title` |

Unknown counts should be `nil`, not `0`.

## Costs

`costs` is your service's price list, in quota units. De-Algo reads `add` to decide whether it can
afford to insert before trying, and `remove` before removing. The cost actually charged is the `cost`
you pass to `account.send` for each request.

## Failure

A function that errors is treated as that operation failing. A failed `add` is retried on later runs,
up to 3 attempts.

See `dealgo/plugins/builtin/youtube/publisher.lua` for a complete publisher, and `api.lua` beside it
for the Data API calls it makes.

**Related:** [Account](Account.md) · [Sources](Sources.md)
