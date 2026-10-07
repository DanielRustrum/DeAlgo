# Aggregation

An **Aggregation** piece is your own algorithm at work — like the one a video site runs on you, but
yours, learning only from you, and only on this machine. Slot it under a **Filter**, a **Sort** or an
**Expire** box.

## What it predicts

Your algorithm learns three things from how you go through items in [Focus mode](../Focus%20Mode.md):

| Signal | It predicts | Learned from |
| --- | --- | --- |
| **Interest** | Would you open it at all | Opening it by clicking its card, staying on it 10 seconds or more, or finishing it — against skipping it at once, or leaving it unopened in a feed for 3 days |
| **Retention** | How much of it you would take in | How far into a video you got, or how long you stayed on a post against how long it takes |
| **Engagement** | How steadily you would stay with it | Retention, less for every time you paused and played again |
| **Saturation** | How much room a feed has for more like it | The share of what you open that is from its source — or carries a tag you name — against the share of what waits in the feed that is |

**Saturation** is not learned: it is worked out as it goes, for the feed the item is on its way to.
100% means the feed holds no more of it than you take in; lower, the feed is already fuller of it
than you would choose. Set **Saturation of** to *Its source*, or to *A tag* and name the tag; an item
without that tag has all the room it wants. It needs as many items opened in Focus mode as the
other signals do before it says anything.

Each prediction is 0–100%. It learns from an item's **source**, **kind**, **tags**, **title words**,
**length** and the **time of day** it went up — a small model you can read: Settings → AI model
shows what it leans towards and away from.

## Under each box

| Under | Does |
| --- | --- |
| **Filter** | Holds back what it predicts below the threshold — for saturation, more of a source or tag a feed already has too much of. The run log says by how much. |
| **Sort** | Puts the batch in order of the prediction, highest first; what is under the threshold goes after everything at or over it. |
| **Expire** | Lets what it predicts below the threshold leave sooner: an item gets less of the box's Timer the further under it falls — never less than a tenth. At or over the threshold, it gets the whole Timer. Needs a Timer in the box. |

Set **Predicts** (the signal) and **Threshold, %** in its panel, which also says where your
algorithm is: learned from how many items and how well it did on ones it was not shown, still
learning, or switched off.

## When it does nothing

An Aggregation piece holds nothing back, keeps the batch in the order it came in, and leaves every
lifetime alone when:

- your algorithm has fewer items than it needs (20 to start with — Settings → AI model);
- you have switched learning off, under Settings → AI model;
- the admin has switched algorithms off for the install, under Admin → Algorithms.

## Learning

It learns again on a run, once a day or every run as you choose, from the last 90 days (also
yours to change) — or straight away with **Learn now**. **Forget everything** clears what it saw and
learned, and it starts again from nothing. Nothing it sees or learns leaves this machine, and it is
not in backups.

**Related:** [Filter](Filter.md) · [Sort](Sort.md) · [Expire](Expire.md) · [Settings](../Settings.md#your-algorithm)
