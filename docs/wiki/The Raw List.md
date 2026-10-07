# The Raw List

Every item Pamphlets has ever seen, what it decided, and why. Open it from the counts at the top of
the Configuration page — each count opens the list filtered to that status.

## Statuses

| Status | Meaning |
| --- | --- |
| `pending` | Found, waiting to be filed. Stays here while it has nowhere to go. |
| `added` | Placed in at least one feed. |
| `skipped` | Every path turned it away. The reason is shown. |
| `ignored` | Set aside — older than the backfill window, or ignored by hand. |
| `failed` | Could not be placed after 3 attempts. The error is shown. |

Filter by status, by watched, or by source, and search titles and source names.

## Row actions

- **Queue** — send a skipped or ignored item through again. It goes to every linked feed it is not
  already in. Use this to backfill an older item.
- **Ignore** — set an item aside for good.
- **Watched** / **Unwatch** — see [Watched Items](Watched%20Items.md).

Each feed an item reached is listed on its row; hover one for its state or error.

## Bulk actions

**Remove N watched from feeds** and **Mark all watched** sit at the top. See
[Watched Items](Watched%20Items.md).

**Related:** [Testing a Flow](Testing%20a%20Flow.md) · [The Run Log](The%20Run%20Log.md)
