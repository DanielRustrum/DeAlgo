# Sources

A source is somewhere Pamphlets watches: any RSS or Atom feed, a newsletter, a JSON API, a form's
queue — or anything a plugin knows how to read. On the canvas, each source is a box that items flow
out of.

Reading sources is free and needs no account: every one of them is read as the feed it publishes.

## Kinds

| Box | What to type | Notes |
| --- | --- | --- |
| **Feed address** | The address of any RSS or Atom feed | Built in. The address must be the feed itself. |
| **Newsletter** | Where a newsletter lives, e.g. `platformer.news` | Built in. Finds the feed for you. See [Newsletters](Newsletters.md). |
| **REST API** | The address of a JSON API that lists things | Built in. Say which fields hold what, or let it guess. See [REST API](REST%20API.md). |
| **Input** | A queue's name, e.g. `feedback` | Built in. Takes what [Form leaflets](Pamphlets.md#forms) send into that queue, each submission once, as an item each time it is polled — wire a Pulse into it. Its panel says which field is each item's title (the first one filled in, otherwise); every field is in the item's words, and its `{ }` port gives every submission as a row. |
| *A plugin's* | Whatever its plugin says, shown in the box | Each plugin's own. Some lookups need a [connected account](../Connecting%20an%20Account.md). |

Plugin kinds appear under **Plugins** in the palette, grouped by plugin. An admin can add more —
see [Plugins](../Plugins.md).

## Adding one

1. Drag the kind you want from the palette.
2. Open the empty box. Type where to watch, or pick one of your existing sources.
3. Optionally set **How far back, in days** for the first check. Blank takes the newest few (3);
   anything older is recorded as *ignored* and never added.
4. Wire it to a [Filter](Filter.md), a [Feed](Feeds.md) or another box.
5. **Switch it on:** a new source starts **paused**. Wiring it does not switch it on — open its box,
   tick **Active**, and save.
6. Wire a [trigger](Triggers.md) into it, or it is never checked.

A feed only lists its newest items — often 10 to 20 — so a long backfill reaches that far and no further.

## The source's panel

- **Active** — on or off.
- **Takes** — which kinds of content to take at all, where the source's plugin publishes more than
  one, each a switch; the plugin may start some of them off, and may let you say what counts as
  which under Settings → Plugins. Turning a kind back on also re-queues what it skipped. A source that publishes one kind of
  thing takes everything; narrow it with a [Filter](Filter.md).
- **Mirror** *(where offered)* — a second address for the same feed, used only when the source refuses
  you. The source's plugin may suggest one.
- **Rename** — see the note on two boxes below.

## How much arrives per run

Each source delivers **at most 5 new items per run**. The rest stay pending and arrive on later runs —
nothing is dropped. To change this for a path, put an **At most** condition on a [Filter](Filter.md).

## One source, two boxes

You can draw the same source twice to send it down two paths. Both boxes share one source — it is
read once — but each has its own name, its own Active switch and its own wires. A run started by a
trigger only fills the paths out of the boxes that trigger is wired to.

## What a source keeps outside its feed

A plugin can also read what a source publishes somewhere its feed does not carry — a page of posts,
say. Where that has no API, the plugin reads the page itself, so:

- it costs no quota and no account, but can stop working if the site changes the page;
- dates may be approximate, when the page only says "5 days ago";
- what it finds goes only into a feed that lives in Pamphlets.

## Removing one

Remove its box. The source and every item it brought go with it — unless another box still
stands for it. Re-adding it later starts fresh, so the backfill applies again.

**Related:** [Newsletters](Newsletters.md) · [Triggers](Triggers.md) · [Filter](Filter.md) ·
[Troubleshooting](../Troubleshooting.md)
