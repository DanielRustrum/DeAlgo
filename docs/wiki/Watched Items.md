# Watched Items

YouTube does not tell apps what you have watched, so Pamphlets only knows what you tell it.

## Marking

- **✓** on a card on [The Feed Page](The%20Feed%20Page.md).
- **Done · next** in [Focus Mode](Focus%20Mode.md).
- **Watched** / **Unwatch** on a row in [The Raw List](The%20Raw%20List.md).
- From the shell: `dealgo watched <video id or URL> …` — see [Command Line](Command%20Line.md).

Watched items are hidden from a feed's default view and from Focus mode.

## Clearing them out

On [The Raw List](The%20Raw%20List.md):

- **Remove N watched from feeds** — deletes those items from every feed they are in, including
  real YouTube playlists. Costs 50 [quota](Quota.md) units per YouTube playlist item.
- **Mark all watched** — marks everything currently in your feeds as watched.

Both ask first. Nothing is ever removed on a schedule or as a side effect of a run.

## Why removed items never come back

The item's record is kept after removal. That record is what stops the next run from finding the
same upload in its source's feed and adding it again.

Deleting an item from a YouTube playlist directly on YouTube sticks too, for the same reason.

**Related:** [The Raw List](The%20Raw%20List.md) · [Expire](Nodes/Expire.md)
