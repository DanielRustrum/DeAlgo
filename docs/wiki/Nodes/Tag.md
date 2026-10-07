# Tag

A Tag box puts a label on every item that passes through it. It turns nothing away.

Open the box and set **Marks it** — e.g. `long reads`. Tags are stored lowercase with spaces
tidied, so `Long  Reads` and `long reads` are the same tag.

## What tags are for

- A [Filter](Filter.md) with a **Has tag** condition lets through only items with that tag, and
  one with **Lacks tag** holds them back. The tag counts from a Tag box anywhere on the same path,
  before or after the Filter.
- Tags appear as pills on the item's card on [The Feed Page](../The%20Feed%20Page.md).

A tag belongs to the item, not to one feed: an item tagged on one path shows the tag everywhere.
Only paths that actually take the item tag it.


## Choosing tags by what each item is

For a source that sends more than one kind of thing — a channel of reviews and news, say — set
**It** to *Choose from these tags, by what each item is*, and list the tags, one per line, with what
each means:

```
reviews — a verdict on one product
news — what happened this week
tutorial — how to do something
```

Each item gets only the tags that fit it — possibly none — up to **At most, per item**. **Chooses
with**:

- **Your AI model** (Settings → [AI model](../Settings.md#ai-model)), if you have chosen one: it is
  asked about the waiting items a batch of 40 at a time, before each run fills its feeds — not once
  per item. It may only choose from your tags. If it cannot be reached, the box chooses on this
  machine instead, that run.
- **On this machine**: a tag fits when a word of its name or meaning is in the item's title or text,
  or — once five or more items carry it already, and five carry another of the box's tags — when
  the item is like those, by the same small model [your algorithm](Aggregation.md) uses.

What it chose is kept on the item and asked once. A Filter's **Has tag** / **Lacks tag** and an
Aggregation's saturation see the tags a box will put on, as well as the ones an item carries.

**Related:** [Filter](Filter.md) · [Decay](Decay.md) · [Expire](Expire.md)
