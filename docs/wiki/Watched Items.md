# Watched Items

The services sources come from do not tell Pamphlets what you have watched, so it only knows what you tell it.

## Marking

- **✓** on a card in [List view](List%20View.md).
- **Done · next** in [Content view](Content%20View.md).
- **Watched** / **Unwatch** on a row in [The Raw List](The%20Raw%20List.md).
- From the shell: `pamphlets watched <video id or URL> …` — see [Command Line](Command%20Line.md).

Watched items are hidden from a feed's default view and from Content view.

## Clearing them out

On [The Raw List](The%20Raw%20List.md):

- **Remove N watched from feeds** — deletes those items from every feed they are in, including
  playlists a plugin keeps on its service, which spends that service's [quota](Quota.md).
- **Mark all watched** — marks everything currently in your feeds as watched.

Both ask first. Nothing is ever removed on a schedule or as a side effect of a run.

## Why removed items never come back

The item's record is kept after removal. That record is what stops the next run from finding the
same upload in its source's feed and adding it again.

Deleting an item from such a playlist directly on its service sticks too, for the same reason.

**Related:** [The Raw List](The%20Raw%20List.md) · [Expire](Nodes/Expire.md)
