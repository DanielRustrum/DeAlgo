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

## Expiring after you watch

Slot an **After watching** piece under the Expire box too, and its Timer starts when you *watch* an
item instead of when it arrives. An item stays until you've watched it, then leaves that long
after.

- Use it for a feed you want to keep until you've seen everything, but not keep forever after.
  With a Timer of 1 day, a video leaves a day after you watch it.
- **Unwatching** an item stops its clock again.
- An unwatched item's card says `leaves after watching`; once it's watched, it says when, like
  `leaves in 23 hours`.
- Adding the piece applies to items already in the feed too. One you watched long enough ago goes
  at the next run.
- A path can have both kinds: a plain Expire box and one counting from the watching. An item leaves
  at whichever comes first.

**Related:** [Decay](Decay.md) · [Feeds](Feeds.md) · [Augmentations](Augmentations.md)
