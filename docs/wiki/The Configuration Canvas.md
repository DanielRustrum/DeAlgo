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
| Operations | [Filter](Filter.md), [Sort](Sort.md), [Tag](Tag.md), [Decay](Decay.md), [Expire](Expire.md), [Deposit and Withdraw](Repositories.md) |
| Augmentations | [Timer, Reset, Alive, Lock](Reading%20Windows.md) and the [conditions](Filter.md) |
| Triggers | [Pulse and Schedule](Triggers.md) |
| Plugins | Each plugin's [sources](Sources.md) and conditions |
| Layout | [Group](Groups.md) |

Rows marked with a green tab are [augmentations](Augmentations.md); the pills under them name the
boxes they fit.

## Wiring

Drag from a box's output (right edge) to another box's input (left edge). Only sensible pairs
connect — a trigger into a source, a source into a filter, a filter into a feed — and De-Algo says
why when it refuses one. Loops are refused.

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
- **Find a group** jumps to a [group](Groups.md).

## Undo

**Ctrl+Z** (or **⌘Z**), or the undo button, takes back the last change — adding a box, moving or
resizing, drawing or removing a wire, or a panel edit. Up to 40 steps. Removing a box cannot be undone.

## Other buttons

- **Load a group** — add a [group](Groups.md) somebody sent you.
- **Run log** — [what runs have been doing](The%20Run%20Log.md).

**Related:** [Sources](Sources.md) · [Feeds](Feeds.md) · [Triggers](Triggers.md) ·
[Testing a Flow](Testing%20a%20Flow.md)
