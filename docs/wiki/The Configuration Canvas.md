# The Configuration Canvas

**Configuration** is your whole setup, drawn as boxes and wires. Items enter at a source, follow the
wires, and land in every feed they can reach. Boxes in between narrow, order or mark them.

```
[Pulse] ──▶ [YouTube channel] ──▶ [Filter] ──▶ [Feed]
                                     └ Longer than 10 min
```

At the top are the **counts** (sources watched, items placed, watched, pending, filtered out,
failed). Each opens [The Raw List](The%20Raw%20List.md) filtered to it. Setup warnings — such as a
Google grant that needs renewing — appear under them.

## The palette

Press **+** to open it. Drag a row onto the canvas, or focus it and press Enter to drop it in the
middle of the view.

| Section | Contains |
| --- | --- |
| *(top)* | **Newsletter**, **Feed address**, **Feed** |
| Operations | [Filter](Nodes/Filter.md), [Sort](Nodes/Sort.md), [Tag](Nodes/Tag.md), [Decay](Nodes/Decay.md), [Expire](Nodes/Expire.md), [Deposit and Withdraw](Nodes/Repositories.md) |
| Augmentations | [Timer, Reset, Alive, Lock](Nodes/Reading%20Windows.md) and the [conditions](Nodes/Filter.md) |
| Triggers | [Pulse and Schedule](Nodes/Triggers.md) |
| Plugins | Each plugin's [sources](Nodes/Sources.md) and conditions |
| Layout | [Group](Nodes/Groups.md) |

Rows marked with a tab icon are [augmentations](Nodes/Augmentations.md); the pills under them name the
boxes they fit.

## Colours

The bar down a box's left edge says what kind of box it is. The palette uses the same colours.

| Colour | Kind |
| --- | --- |
| Violet | Triggers — Pulse, Schedule |
| Green | Sources — channels, newsletters, feed addresses. A plugin may give its sources one of a few [other colours](Creating%20A%20Plugin/Sources.md#colour) instead: YouTube's are red, Bluesky's sky blue |
| Amber | Filter |
| Blue | Sort |
| Teal | Tag, Decay, Expire — they mark what passes and turn nothing away |
| Brown | Deposit and Withdraw |
| Terracotta | Feed |
| Grey | An augmentation not yet slotted in; once it is, it takes the colour of its box |

## Wiring

Drag from a box's output (right edge) to another box's input (left edge). Only sensible pairs
connect — a trigger into a source, a source into a filter, a filter into a feed — and De-Algo says
why when it refuses one. Loops are refused.

Each kind of wire has its own port, marked inside the dot:

| Mark | Carries | From → to |
| --- | --- | --- |
| ⚡ bolt | A signal to run | Trigger → source or Withdraw |
| ▶ play | Items, down a path | Source → filter, sort, feed… |
| Sheet of print | A feed or words, onto a page | Feed → Feed or Link leaflet; [Text](Nodes/Text.md) → Text leaflet |
| `{ }` braces | JSON, to be drawn | Source → operations → [Format](Nodes/Format.md) → Chart leaflet |

A [REST API](Nodes/REST%20API.md) source gives data only: its one output is `{ }`.

A box that can connect more than one way shows a port for each. Sources, the operation boxes
(Filter, Sort, Tag, Decay, Expire) and Withdraw have a ▶ port and a `{ }` port on each side they
use: items and data can run through the same box at once, down separate wires — even between the
same two boxes. Drag from the port of the kind you want. Once one port on a side is wired, the
others there fade; they still take a wire.

Only ▶ and ⚡ wires are paths. Data wires never change what is collected or where it goes.

Click a wire to select it, then press the **✕** that appears on it to remove it.

## Boxes

Click a box to open its panel, change it, and press **Save**. Every box has an **Active** switch:
a switched-off box carries nothing.

If a source or feed has two boxes, renaming or switching off one leaves the other alone. With only
one box, renaming or switching it off renames or pauses the source or feed itself.

## Selecting and removing

- **Shift-click** boxes, or **Shift-drag** across empty canvas, to select several.
- **Delete** or **Backspace** removes the selection, after asking. **Escape** clears it.
- Removing a source or feed box also removes the source or feed behind it — unless another box
  still stands for it.

## Moving around

- **Drag empty canvas** to pan. It has no edges.
- **Scroll** to zoom (30%–250%), keeping the point under the pointer still. Scrolling over a panel
  scrolls the panel instead.
- **Find a group** jumps to a [group](Nodes/Groups.md).

## Undo

**Ctrl+Z** (or **⌘Z**), or the undo button, takes back the last change — adding a box, moving or
resizing, drawing or removing a wire, or a panel edit. Up to 40 steps. Removing a box cannot be undone.

## Other buttons

- **Load a group** — add a [group](Nodes/Groups.md) somebody sent you.
- **Run log** — [what runs have been doing](The%20Run%20Log.md).

**Related:** [Sources](Nodes/Sources.md) · [Feeds](Nodes/Feeds.md) · [Triggers](Nodes/Triggers.md) ·
[Testing a Flow](Testing%20a%20Flow.md)
