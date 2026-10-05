# Expire

An Expire box takes items out of a feed a set time after they arrive. It turns nothing away.

Slot a **Timer** under it for the lifetime — minutes, hours, days or weeks. Without one it does nothing.

## How it behaves

- The clock starts when the item lands in the feed.
- Expired items are removed at the next run, so up to about 30 minutes late.
- Removal from a YouTube playlist deletes the playlist item, costing 50 [quota](../Quota.md) units.
- The item stays in your history and is never re-added. Other feeds holding it are untouched.
- Adding an Expire box also applies to items **already** in the feed, counted from when each arrived.
- If several Expire boxes apply, the **shortest** lifetime wins.
- The card shows when it leaves: `leaves in 2 days`.

## Expiring once you watch

Slot an **After watching** piece under the Expire box, and an item leaves once you've *watched*
it, at the next run. It needs no Timer.

- Use it for a feed you want to keep until you've seen everything, and no longer.
- With a **Timer** slotted in as well, both apply: an item leaves when you watch it, or when the
  Timer runs out from its arrival — whichever comes first. With a Timer of 1 week, a video goes as
  soon as you watch it, and an unwatched one still goes after a week.
- **Unwatching** an item before the next run keeps it.
- An unwatched item's card says `leaves once watched`, beside `leaves in …` when a Timer applies.
- Adding the piece applies to items already in the feed too: anything already watched goes at the
  next run.

**Related:** [Decay](Decay.md) · [Feeds](Feeds.md) · [Augmentations](Augmentations.md)
