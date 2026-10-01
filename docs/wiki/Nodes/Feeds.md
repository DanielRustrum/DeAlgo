# Feeds

A feed is where items end up. You read feeds on [The Feed Page](../The%20Feed%20Page.md) and in
[Focus Mode](../Focus%20Mode.md).

## Two kinds

| | Lives in De-Algo | Backed by a YouTube playlist |
| --- | --- | --- |
| Make it | Drag **Feed** from the palette and name it | **Settings → Feeds on YouTube** |
| Holds | Anything: videos, posts, Reddit, RSS, newsletters | YouTube videos only |
| Needs | Nothing | A connected Google account and [quota](../Quota.md) |

A YouTube-backed feed can be a new playlist (private, unlisted or public) or one you already have.
Non-YouTube items reaching it are turned away with a reason.

Without a connected account a YouTube-backed feed is marked *local only* and collects inside De-Algo.
Its items are written to the playlist after you [connect](../Connecting%20YouTube.md).

## Limits

Set on the feed's box or its page. `0` means no limit.

- **Max items** — once the feed holds more, its oldest are removed. A rolling feed.
- **Max added per run** — anything over this waits for the next run. Nothing is dropped.

## A feed's own page

Open a feed box's panel and follow its link, or go to `/feeds/<id>`.

- **Rename** — also renames the YouTube playlist (50 quota units). If YouTube refuses, the name
  still changes here and says so.
- **Tags** — free-form labels. The Feed page's search matches them.
- **Filling** — pause or resume the feed without touching what is in it; set its limits.
- **Filled by** — tick a source to wire it straight to this feed; untick to remove its wires. Only
  direct wires show here; a source reaching this feed through a [Filter](Filter.md) does not.
- **Unlink from YouTube** — keep the feed and its items, drop the playlist behind it. The playlist
  on YouTube is left as it is.
- **Remove feed** — delete the feed and its record of what went in. A YouTube playlist is left as it is.

## When one item reaches several feeds

It is placed in each. In YouTube-backed feeds that costs 50 quota units per playlist. De-Algo
records every placement, so an item is never added to the same feed twice.

## Fill order

When quota runs short, sources and feeds are served in the order you added them. There is currently
no control to reorder them.

**Related:** [Sources](Sources.md) · [The Configuration Canvas](../The%20Configuration%20Canvas.md) ·
[Expire](Expire.md) · [Reading Windows](Reading%20Windows.md)
