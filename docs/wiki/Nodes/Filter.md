# Filter

A Filter box lets some items through and holds the rest back, on the paths that pass through it.
Other paths from the same source are unaffected.

A Filter does nothing by itself. Slot **conditions** under it — one piece per condition. An item gets
through only if **every** condition agrees.

```
[Source] ──▶ [Filter] ──▶ [Feed]
               ├ Longer than 10 minutes
               └ Title lacks "sponsored"
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
| **Has tag** | Items with any of these tags | One or more tags, commas between |
| **Lacks tag** | Items with none of these tags | One or more tags, commas between |
| **At most** | Up to this many per run; the rest wait | A number |

**Matching text:** a case-insensitive regular-expression search. Plain words match anywhere in the
text, but characters like `.`, `?`, `(` and `|` are regex syntax — `cats|dogs` matches either.
Videos are matched on their title; posts on their whole text; articles on title and summary.

**Lengths** are known only for items whose source gives one — some only once a plugin has read their
details, which may need a [connected account](../Connecting%20an%20Account.md). An item with no known
length passes length conditions.

**Tags:** **Has tag** and **Lacks tag** see tags from a [Tag](Tag.md) box anywhere on the same path,
as well as tags the item already has — from a box or put on by hand. Type them with commas between,
or pick them from the tags listed under the field: every tag a Tag box marks with or an item
carries. Capitals and extra spaces don't matter.

## Plugin conditions

Plugins can add conditions of their own, listed under **Plugins** in the palette once installed (see
[Plugins](../Plugins.md)), each with its own value to set. A condition from a source plugin judges
only that plugin's items and lets everything else through; one from a plugin with no sources judges
every item. A count nobody has read yet — views, likes — counts as unknown, and passes.

## When conditions overlap

- Under one Filter, two conditions of the **same kind** do not both apply: the one nearest the box wins.
- Across two Filters on one path, a setting in the Filter nearer the feed overrides the same setting
  in the earlier one. Different settings all apply.
- Plugin conditions always all apply.

## Seeing what it does

Open a Filter's panel to see recent items it let through and held back, and why. To check a whole
path, use [Testing a Flow](../Testing%20a%20Flow.md).

**Related:** [Augmentations](Augmentations.md) · [Tag](Tag.md) · [Sort](Sort.md)
