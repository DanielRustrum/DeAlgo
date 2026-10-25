# Feeds

A feed is where items end up. You read feeds in [List view](../List%20View.md) and in
[Content view](../Content%20View.md).

## Two kinds

| | Lives in Pamphlets | Backed by a playlist on a service |
| --- | --- | --- |
| Make it | Drag **Feed** from the palette and name it | The plugin's block under **Settings → Plugins** |
| Holds | Anything: videos, posts, articles, newsletters | Only that plugin's own items |
| Needs | Nothing | A plugin that publishes, a [connected account](../Connecting%20an%20Account.md), and [quota](../Quota.md) |

A feed backed by a service can be a new playlist there or one you already have. Items from anywhere
else reaching it are turned away with a reason.

Without a connected account such a feed is marked *local only* and collects inside Pamphlets.
Its items are written to the playlist after you [connect](../Connecting%20an%20Account.md).

## Limits

Set on the feed's box or its page. `0` means no limit.

- **Max items** — once the feed holds more, its oldest are removed. A rolling feed.
- **Max added per run** — anything over this waits for the next run. Nothing is dropped.

## A feed's own page

Open a feed box's panel and follow its link, or go to `/feeds/<id>`.

- **Rename** — also renames the playlist behind it, if there is one (which spends quota). If the
  service refuses, the name still changes here and says so.
- **Tags** — free-form labels. List view's search matches them.
- **Filling** — pause or resume the feed without touching what is in it; set its limits.
- **Filled by** — tick a source to wire it straight to this feed; untick to remove its wires. Only
  direct wires show here; a source reaching this feed through a [Filter](Filter.md) does not.
- **Unlink** — keep the feed and its items, drop the playlist behind it. The playlist on the service
  is left as it is.
- **Remove feed** — delete the feed and its record of what went in. A playlist behind it is left as
  it is.

## When one item reaches several feeds

It is placed in each. In feeds backed by a service each placement spends quota. Pamphlets
records every placement, so an item is never added to the same feed twice.

## Fill order

When quota runs short, sources and feeds are served in the order you added them. There is currently
no control to reorder them.

**Related:** [Sources](Sources.md) · [The Configuration Canvas](../The%20Configuration%20Canvas.md) ·
[Expire](Expire.md) · [Reading Windows](Reading%20Windows.md)
