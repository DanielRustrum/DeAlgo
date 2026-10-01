# The Graph

The Configuration canvas is the routing table. `services/graph.py` owns it; the sync engine asks it
for routes and never reads wiring directly.

## Vocabulary

| Term | Is | Stored as |
| --- | --- | --- |
| **Box** | Something on a path or that starts one | `graph_node`, `attached_to` NULL |
| **Wire** | A directed connection between boxes | `graph_edge` |
| **Piece** (augmentation) | Something slotted *under* a box that changes what it does | `graph_node` with `attached_to` = host |
| **Route** | One path from a source box to a feed or Deposit | `graph.Route`, computed |

## Box kinds and what may be wired to what

`ALLOWED` in `graph.py`:

| From | May wire to |
| --- | --- |
| `trigger` | `source`, `withdraw` |
| `source`, `withdraw`, `filter`, `sort` | middles (`filter`, `sort`, `decay`, `expire`, `tag`) and ends (`feed`, `deposit`) |
| `decay`, `expire`, `tag` | middles and ends |
| `feed`, `deposit`, `group`, pieces | nothing |

`connect()` also refuses:

- a wire to itself;
- a non-YouTube source straight into a YouTube playlist (it could never carry anything);
- a loop — `_reaches(target, source)` walks forward from the target first.

Duplicate wires return the existing edge.

## Pieces

Pieces form a **chain** under a host: a piece may be slotted under another piece, and all of them
belong to the box at the top.

| Piece | Allowed under | Means |
| --- | --- | --- |
| `timer` | `feed`, `decay`, `expire` | Sitting length / time per item / lifetime |
| `reset`, `alive` | `feed` | When a sitting re-arms / hours a feed may open |
| `lock` | `decay` | The Decay timer cannot be paused |
| `has-words`, `lacks-words`, `longer-than`, `shorter-than`, `carrying`, `at-most` | `filter` | Conditions |
| `order` | `sort` | What to order by |
| `rule` | `filter` or `sort`, per the plugin's `under` | A plugin's `keep` or `rank` |

`PIECE_HOSTS` holds this table; `piece_hosts(piece)` asks the registry for `rule` pieces.

- `attach()` checks the **top** of the chain, not the piece dropped onto, and refuses rings.
- `detach()` and deleting a piece **close up** the chain (`_close_up`): what was below moves up.
- `pieces_under(host)` returns the chain breadth-first, **nearest first**. The nearest piece has the
  last word.

Condition pieces store their value in the same column the old box field used
(`title_include`, `min_duration_sec`, …), so `filter_rules()` simply layers each piece's
`overrides`, far end first.

## Finding routes — `routes(session, owner)`

1. Load all nodes and edges; build `out[node] → [targets]`.
2. For each **enabled** `source` box with a channel, depth-first `_walk`:
   - Into a `feed` (enabled, with a playlist) or a named, enabled `deposit` → emit a `Route`.
   - Into an enabled middle box → recurse, appending it to `filters`, `sorts` or `stamps` by kind,
     and always to `walked`.
   - A disabled box ends the path. Nothing passes through it.
   - `seen` is **per path**, so two paths may share a box; only a loop stops a walk.
3. `_slot_in`: compute `pieces_under` once per slotted box, hand every route the same `slots` map,
   and collect `checks` — enabled `rule` pieces under the route's Filters.
4. `_once_each`: drop routes whose signature (channel, feed, store, filters, sorts, checks, stamps)
   repeats. Two boxes for one channel wired identically are one route.

Withdraw boxes are walked the same way by `paths_from` when a pull runs.

## What a route answers

| Method / field | Answer |
| --- | --- |
| `effective()` | The channel's own filter columns with each Filter's `filter_rules` laid over, in path order |
| `checks` | Plugin conditions to ask per item |
| `order` | The `order` or `rule` piece under the **last** Sort — nearest the feed wins |
| `stamps` | Decay/Expire/Tag boxes, read after acceptance |
| `source` | The box it started from (a channel can have several) |

## One box or several

A channel or feed may have several boxes. `stands_alone(node)` is true only for the sole box; only
then does renaming or switching a box write through to the channel or playlist. With several, each
box's switch affects only its own paths.

`channel.playlists` is recomputed by `refresh_membership` from direct source→feed wires after every
wiring change.

## First open

`load()` lays out an existing setup the first time (`_lay_out_existing`: one box per channel and
feed, one wire per existing link) and adds a box for any channel or feed created since
(`_add_missing`), unwired.

## Groups

A `group` node is a background rectangle. Moving it moves the nodes inside. Export
(`export_group`, `GROUP_FORMAT = 2`) stores positions relative to the group, channels by their id,
feeds by name; import recreates them.

## Testing a flow — `try_it`

Pushes recent items through the routes a trigger reaches (narrowed by source **box**) and through
any Withdraw boxes it pulls, and reports per box what passed and what was held and why. Writes
nothing and calls no API.

**Related:** [The Sync Engine](The%20Sync%20Engine.md) · [Reading Windows](Reading%20Windows.md) ·
[Algorithms](Algorithms.md)
