# Algorithms

Every non-trivial algorithm, where it lives, and its cost. `N` = nodes, `E` = wires, `P` = paths,
`I` = pending items.

## Route finding
`graph.routes` → `_walk` · depth-first search from each enabled source box.

- Per-path `seen` set: a box may appear on many paths; only revisiting a box **on the same path**
  (a loop) stops the walk. Loops are also refused when drawn (`_reaches`).
- Enabled middle boxes extend the path; a disabled box ends it; feeds and named deposits emit a
  route.
- Cost: proportional to the number of distinct paths, `O(P · path length)`. Canvases are small
  (tens of boxes), so this is recomputed per run rather than cached.

## Route de-duplication
`_once_each` · hash of `(channel, feed, store, filters, sorts, checks, stamps)`; first wins. `O(P)`.

## Piece chains
`pieces_under(host)` · build `attached_to → children` once (`O(N)`), then breadth-first from the
host, nearest first, with a `seen` set against legacy rings. `host_of` walks up the chain.
`attach` walks up from the target to refuse rings.

## Rule layering
`filter_rules` · fold condition pieces far-to-near into a dict (nearest overwrites).
`Route.effective` · channel defaults, then each Filter's rules in path order (later overwrites).

## Batch ordering
`reorder` / `_sorter`:

1. For each pending item, the first route with an `order` gives key `(sort box id, ±value)`
   (descending negates).
2. Stable sort of the batch by `(key or (0, 0), original index)`.

Items under different Sort boxes stay grouped by box; unsorted items keep their order (channel
priority, then oldest first). Values: published timestamp, duration, views, likes, or a title prefix
encoded as a number (first 8 characters, base 256). Plugin orderings use `rank`. `O(I log I)`.

## Trigger due-ness
`When.due` · pulse: `now ≥ last + every`; schedule: APScheduler `CronTrigger.get_next_fire_time`
after `last` ≤ `now`. Weekday field rewritten to names first (cron counts from Sunday, APScheduler
from Monday).

## Reading windows
`window_state` · see [Reading Windows](Reading%20Windows.md). `_fired_between` steps past the
firing equal to the sitting start so it is not counted twice. `_next_alive` computes each
stretch's next start directly rather than scanning minutes.

## Rate-limit back-off
`patience.note` / `hold` · per-host monotonic deadline, max-merge, capped at an hour; read from
`Retry-After`, `X-RateLimit-Remaining`/`-Reset`, or refusal status.

## Item identity
Plugin-given id if any, else `item-` + SHA-1(`channel_id|guid`)[:24]. Source id in the hash keeps
two feeds' identical guids apart.

## Feed discovery
`newsletter.candidates` · declared feeds, then fixed paths on the host and its `www.` sibling,
de-duplicated, capped at 10; first that parses as a feed wins.

## Archive vetting
`fetching.archive._members` · stream the tar, keep regular files only, reject absolute and `..` paths, count
files and running unpacked size against limits before reading each.

## Quota day
`quota.quota_day` · the current date in `America/Los_Angeles`; `next_reset` is the next Pacific
midnight in UTC.

## Password and key derivation
scrypt (`hashlib.scrypt`) for passwords (N = 2¹⁴) and migration keys (N = 2¹⁵); SHA-256 for
session-token lookup; Fernet for migration files.
