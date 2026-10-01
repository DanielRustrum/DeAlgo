# Expire

An Expire box takes items out of a feed a set time after they arrive. It turns nothing away.

Slot a **Timer** under it for the lifetime — minutes, hours, days or weeks. Without one it does nothing.

## How it behaves

- The clock starts when the item lands in the feed.
- Expired items are removed at the next run, so up to about 30 minutes late.
- Removal from a YouTube playlist deletes the playlist item, costing 50 [quota](Quota.md) units.
- The item stays in your history and is never re-added. Other feeds holding it are untouched.
- Adding an Expire box also applies to items **already** in the feed, counted from when each arrived.
- If several Expire boxes apply, the **shortest** lifetime wins.
- The card shows when it leaves: `leaves in 2 days`.

**Related:** [Decay](Decay.md) · [Feeds](Feeds.md) · [Augmentations](Augmentations.md)
