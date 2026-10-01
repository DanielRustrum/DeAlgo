# Sort

A Sort box sets the order items are **added** in, on the paths through it.

It does nothing by itself. Slot one **Order** piece under it and choose:

| Order by | Ends |
| --- | --- |
| When it went up | Newest first / Oldest first |
| How long it is | Longest first / Shortest first |
| How many have watched it | Most / least watched first |
| How many liked it | Most / least liked first |
| Its title | A to Z / Z to A |

A plugin can offer its own orderings, which slot under a Sort the same way. The Shape plugin's
**How much there is to read** orders by length of text.

## What it changes

- **YouTube playlists** keep the order items were added in, so the Sort is what you see there.
- **When a cap or quota stops a run partway**, the Sort decides which items got in first.
- **Not** the Feed page or Focus mode: those order by publish date (oldest or newest first, per feed).

## Details

- With several Sort boxes on one path, the one nearest the feed decides.
- View and like counts are read with video details, which needs a
  [connected account](../Connecting%20YouTube.md) or an API key. Items without them sort last.

**Related:** [Filter](Filter.md) · [Feeds](Feeds.md) · [Augmentations](Augmentations.md)
