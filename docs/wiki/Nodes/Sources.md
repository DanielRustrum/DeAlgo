# Sources

A source is somewhere Pamphlets watches: a YouTube channel, a subreddit, a newsletter, any RSS or Atom
feed. On the canvas, each source is a box that items flow out of.

Reading sources is free and needs no account: every one of them is read as the feed it publishes.

## Kinds

| Box | What to type | Notes |
| --- | --- | --- |
| **Feed address** | The address of any RSS or Atom feed | Built in. The address must be the feed itself. |
| **Newsletter** | Where a newsletter lives, e.g. `platformer.news` | Built in. Finds the feed for you. See [Newsletters](Newsletters.md). |
| **REST API** | The address of a JSON API that lists things | Built in. Say which fields hold what, or let it guess. See [REST API](REST%20API.md). |
| **YouTube channel** | `@handle`, a channel URL, or a `UC…` id | YouTube plugin. `@handle` and custom URLs need a [connected account](../Connecting%20YouTube.md); a `UC…` id or `/channel/` URL does not. |
| **Subreddit** | `r/python`, a subreddit URL, or just `python` | Reddit plugin. |
| **Bluesky account** | `@name.bsky.social` or a profile URL | Bluesky plugin. |
| **Newsletter** *(Substack)* | `name.substack.com` | Substack plugin. Same box name as the built-in one; the built-in Newsletter box also handles Substack. |

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

A feed only lists its newest items (YouTube about 15), so a long backfill reaches that far and no further.

## The source's panel

- **Active** — on or off.
- **Takes** — which kinds of content to take at all, where the source's plugin publishes more than
  one. YouTube's are **Videos**, **Shorts**, **Live** (streams and premieres) and **Posts** (community
  posts); new channels take Videos and Posts, not Shorts or Live. How long a video can be and still
  count as a Short is yours to set, in the YouTube block under Settings → Plugins (60 seconds by
  default). Turning a kind back on also re-queues what it skipped. A source that publishes one kind of
  thing takes everything; narrow it with a [Filter](Filter.md).
- **Mirror** *(where offered)* — a second address for the same feed, used only when the source refuses
  you. Reddit suggests one.
- **Rename** — see the note on two boxes below.

## How much arrives per run

Each source delivers **at most 5 new items per run**. The rest stay pending and arrive on later runs —
nothing is dropped. To change this for a path, put an **At most** condition on a [Filter](Filter.md).

## One source, two boxes

You can draw the same source twice to send it down two paths. Both boxes share one source — it is
read once — but each has its own name, its own Active switch and its own wires. A run started by a
trigger only fills the paths out of the boxes that trigger is wired to.

## YouTube community posts

There is no API for them, so Pamphlets reads the channel's Posts page:

- costs no quota and no account, but can stop working if YouTube changes the page;
- dates are approximate (YouTube only says "5 days ago");
- a post can never go into a YouTube playlist, only into a feed that lives in Pamphlets.

## Removing one

Remove its box. The source and every item it brought go with it — unless another box still
stands for it. Re-adding it later starts fresh, so the backfill applies again.

**Related:** [Newsletters](Newsletters.md) · [Triggers](Triggers.md) · [Filter](Filter.md) ·
[Troubleshooting](../Troubleshooting.md)
