# Decay

A Decay box sets how long you get with each item that passes through it, in
[Content view](../Content%20View.md). It turns nothing away.

```
[Source] ──▶ [Decay] ──▶ [Feed]
               ├ Timer: 3 minutes
               └ Lock
```

Slot a **Timer** under it for the time. Without one it does nothing. Add a **Lock** under it and the
countdown cannot be held or paused.

## How it behaves

- Applies to **posts and articles** in Content view: a countdown runs and moves on when it ends.
  Videos are not timed; they always play to the end.
- Belongs to the item, not to one feed.
- If several Decay boxes apply to one item, the **shortest** time wins.
- The card shows the time, with `· no pause` when locked.

**Related:** [Content view](../Content%20View.md) · [Augmentations](Augmentations.md) · [Expire](Expire.md)
