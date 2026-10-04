# The Feed Page

**Feed** is where you read. `/` opens it. It has two levels: a shelf of every feed, and each feed's
own page.

## The shelf

Every feed is a tile. A tile shows:

- a mosaic of its newest unwatched items;
- how many are waiting (the number in the corner);
- when something last arrived;
- its tags.

A feed that is paused, local only, or shut by a [reading window](Nodes/Reading%20Windows.md) says
so on its tile. Click a tile to open the feed.

- **★ Favourites:** press the star on a tile to put that feed in *Favourites*, at the top of the
  shelf. Press it again to put it back. A new favourite joins the end of the favourites.
- **Search** matches feed names and tags. **Tag chips** under it show only the feeds wearing one
  tag; **All** shows every feed again. Set tags on a feed's settings page; see
  [Feeds](Nodes/Feeds.md).
- **Sort**: *My order* (your own arrangement, the default), *Name*, *Most waiting*, or *Latest
  arrivals*. Sorting is only a view and changes nothing. Favourites stay on top whatever the sort.
- **Arrange** puts the shelf in your own order and lets you change it:
  - **drag** a tile to where you want it;
  - **⇤ ← → ⇥** move it to the start, one place earlier, one place later, or to the end. These
    work from the keyboard and without JavaScript.
  - Favourites and the rest are each arranged within themselves; star or unstar a feed to move it
    from one to the other.
  - Press **Done** when you've finished.
- **Focus ▶** at the top plays every feed's unwatched items in one queue.

Your arrangement is only where feeds sit on this page. The order feeds are *filled* in when the
quota runs short is each feed's **priority**, on its settings page, and arranging never changes
it.

## A feed's own page

`/feed/<id>`, reached from its tile. **Feeds** at the top leads back to the shelf, and the star
beside its name works the same as on the tile. Its items are cards: a thumbnail, the age, and
the length or kind. Click a thumbnail to start [Focus Mode](Focus%20Mode.md) at that item.

Each feed remembers its own choices:

- **unwatched / everything**: hide watched items (the default), or show them dimmed.
- **oldest first / newest first**: oldest first matches the order a playlist reads in.
- **Focus ▶**: play this feed straight through.
- **Clear**: take everything out of this feed, watched or not, after you confirm. A feed backed
  by a real playlist is cleared there too when your account is connected. Each removal costs quota,
  and Clear stops and says so if the day's allowance runs out. Cleared items stay in your history
  and in any other feed, and the next run doesn't put them back.

An old link to `/feed?playlist=<id>` opens that feed's page.

## What a card shows

- **Posts** show their first image, or their opening words if they have none.
- **Items from other sources** (Reddit, RSS, newsletters) show where they came from instead of a length.
- **Marks** from the boxes the item passed: its [tags](Nodes/Tag.md), the time a [Decay](Nodes/Decay.md) box
  gave it (`· no pause` if locked), and when an [Expire](Nodes/Expire.md) box takes it out (`leaves in 2 days`).

Hover a card (or tap, on touch screens) for **✓** to mark it watched and **↗** to open it at its source.

## A shut feed

A feed with [reading windows](Nodes/Reading%20Windows.md) can be closed. Its tile says *shut* and
when it opens; its page shows the rule you set. A shut feed is never hidden. Opening a feed's page is
what starts a timed sitting; looking at the shelf doesn't.

## Live updates

When a run finishes, the shelf and an open feed page refresh on their own.

**Related:** [Focus Mode](Focus%20Mode.md) · [Watched Items](Watched%20Items.md) · [Feeds](Nodes/Feeds.md)
