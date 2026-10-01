# Filter

A Filter box lets some items through and holds the rest back, on the paths that pass through it.
Other paths from the same source are unaffected.

A Filter does nothing by itself. Slot **conditions** under it — one piece per condition. An item gets
through only if **every** condition agrees.

```
[Source] ──▶ [Filter] ──▶ [Feed]
               ├ Longer than 10 minutes
               └ No Shorts            (YouTube)
```

## Adding a condition

Drag a condition from **Augmentations** (built in) or **Plugins** (from a plugin) onto the bottom of a
Filter box. Open it to set its value. See [Augmentations](Augmentations.md) for slotting and removing pieces.

## Built-in conditions

| Condition | Lets through | Value |
| --- | --- | --- |
| **Title has** | Items whose text matches | Words, or a regular expression |
| **Title lacks** | Items whose text does not match | Words, or a regular expression |
| **Longer than** | Videos at least this long | Amount and unit |
| **Shorter than** | Videos at most this long | Amount and unit |
| **Carrying** | Items with this tag | A tag put on by a [Tag](Tag.md) box |
| **At most** | Up to this many per run; the rest wait | A number |

**Matching text:** a case-insensitive regular-expression search. Plain words match anywhere in the
text, but characters like `.`, `?`, `(` and `|` are regex syntax — `cats|dogs` matches either.
Videos are matched on their title; posts on their whole text; articles on title and summary.

**Lengths** are known only for YouTube videos, and only after their details are read — which needs a
[connected account](../Connecting%20YouTube.md) or an API key. An item with no known length passes
length conditions.

**Carrying** sees tags from a Tag box anywhere on the same path, as well as tags the item already has.

## Plugin conditions

Shipped plugins add these. A source plugin's conditions judge only that source's items and let
everything else through; Shape's judge every item.

| Plugin | Condition | Lets through | Default |
| --- | --- | --- | --- |
| YouTube | No videos / No Shorts / No live / No posts | Everything except that kind | |
| YouTube | Only Shorts | Shorts only | |
| YouTube | Watched enough | Videos with at least N views | 1000 |
| YouTube | Well liked | Videos with at least N likes | 100 |
| Reddit | Self posts | Posts with at least N characters of writing | 80 |
| Reddit | Asks a question | Posts that ask something, with or without a `?` | |
| Bluesky | Said something | Posts with at least N characters, so not bare link shares | 24 |
| Substack | Long read | Pieces with at least N characters | 1200 |
| Shape | Long enough | Items at least N minutes long | 5 |
| Shape | Has words | Items whose title and text reach N characters | 40 |
| Shape | Not shouting | Titles with at most N% capitals | 60 |

A view or like count nobody has read yet counts as unknown, and passes.

## When conditions overlap

- Under one Filter, two conditions of the **same kind** do not both apply: the one nearest the box wins.
- Across two Filters on one path, a setting in the Filter nearer the feed overrides the same setting
  in the earlier one. Different settings all apply.
- Plugin conditions always all apply.

## Seeing what it does

Open a Filter's panel to see recent items it let through and held back, and why. To check a whole
path, use [Testing a Flow](../Testing%20a%20Flow.md).

**Related:** [Augmentations](Augmentations.md) · [Tag](Tag.md) · [Sort](Sort.md)
