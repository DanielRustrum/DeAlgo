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
| *(top)* | **Newsletter**, **Input**, **REST API**, **Feed address**, **Feed** |
| Operations | [Filter](Nodes/Filter.md), [Sort](Nodes/Sort.md), [Tag](Nodes/Tag.md), [Decay](Nodes/Decay.md), [Expire](Nodes/Expire.md), [Deposit and Withdraw](Nodes/Repositories.md), [Activate and Return](Nodes/Triggers.md#activation-and-activate) |
| Augmentations | [Timer, Reset, Alive, Lock](Nodes/Reading%20Windows.md) and the [conditions](Nodes/Filter.md) |
| Triggers | [Pulse, Schedule and Activation](Nodes/Triggers.md) |
| Plugins | Each plugin's [sources](Nodes/Sources.md) and conditions |
| Pamphlets | [Pamphlet and its leaflets](Nodes/Pamphlets.md), with **Form inputs** — the fields of a [Form leaflet](Nodes/Pamphlets.md#forms) — and **Charts**, a leaflet for each kind of chart, folded inside |
| Layout | [Group](Nodes/Groups.md), [Canvas, Relay and Comment](Nodes/Canvases%20and%20Relays.md) |

Rows marked with a tab icon are [augmentations](Nodes/Augmentations.md); the pills under them name the
boxes they fit.

## Colours

The bar down a box's left edge says what kind of box it is. The palette uses the same colours.

| Colour | Kind |
| --- | --- |
| Violet | Triggers — Pulse, Schedule, Activation — and Activate and Return |
| Green | Sources — channels, newsletters, feed addresses. A plugin may give its sources one of a few [other colours](Creating%20A%20Plugin/Sources.md#colour) instead: YouTube's are red, Bluesky's sky blue |
| Amber | Filter |
| Blue | Sort |
| Teal | Tag, Decay, Expire — they mark what passes and turn nothing away |
| Brown | Deposit and Withdraw |
| Terracotta | Feed |
| Grey | An augmentation not yet slotted in; once it is, it takes the colour of its box |

## Wiring

Drag from a box's output (right edge) to another box's input (left edge). Only sensible pairs
connect — a trigger into a source, a source into a filter, a filter into a feed — and Pamphlets says
why when it refuses one. Loops are refused.

Each kind of wire has its own port, marked inside the dot:

| Mark | Carries | From → to |
| --- | --- | --- |
| ⚡ bolt | A signal to run | Trigger → source or Withdraw |
| ▶ play | Items, down a path | Source → filter, sort, feed… |
| Sheet of print | A feed or words, onto a page | Feed → Feed or Link leaflet; [Text](Nodes/Text.md) → Text leaflet |
| `{ }` braces | JSON, to be drawn | Source → operations → a chart leaflet, or through a [Format](Nodes/Format.md) box |

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

## The editor

**Double-click** a box, or press **Open editor** in its panel, to see what goes through it.

On a **Transform**, **Format** or **Text** box, or a chart leaflet, the editor has three panes:

- **Input** on the left: what reaches the box — the data down its `{ }` wire, or the items down its
  ▶ wires read as rows.
- **Settings** in the middle.
- **Output** on the right: what the box gives out with those settings, worked out again as you
  change them, before anything is saved. A Format box or chart leaflet shows its chart here; a
  Text box shows what it last wrote, with **Write now**.

Each side can be shown as **Fields** (every path in the rows, what kind of thing is there, and an
example), as a **Table**, or as **JSON**. Drag a field — from the list or a table heading — onto a
setting, or press it to put it in the setting you were last in. **Save** keeps the settings; ✕ or
Esc closes without saving.

### Fields in settings

A field goes into a setting written in double braces — `{{ data.author }}` — and is highlighted, so
what is read from the data stands apart from plain text. Under the setting, after `=`, is what it
comes to with the data on the left.

- In a setting that names one field (a chart's or Format box's rows, label, number or series), the
  field replaces what was there. A bare path, as settings were written before, still works.
- In words — a chart leaflet's heading, what a Text box is told — it goes in where the cursor is,
  among the rest: `Videos this week: {{ count }}`. Each field is filled from the data as it is,
  or else from its first row; one that is not there is left blank.

On a source, an operation (Filter, Sort, Tag, Decay, Expire), a Deposit or Withdraw, or a feed,
**Input & output** shows the two sides only: those boxes are set in their panel. A source shows
only what it gives out.

## How wires are drawn

Click a wire to pick it. Beside its ✕ is how it is drawn:

- **Curve** — a smooth S from port to port, the way wires start out.
- **Straight** — a straight line.
- **Square** — straight out of each port, then across in right angles. Its middle segment — the one
  not hanging off a port — can be **dragged**: across, if it runs up and down, or up and down, if it
  runs across; the cursor says which. Where it was dragged to is kept as a distance from its usual
  place, so it keeps its shape when the boxes move. A wire that leaves sideways and arrives from
  above (an L) gains a segment once its upright is dragged. Ctrl+Z puts it back.
- **Around boxes** — a path found round every box in its way (A\* over a grid), keeping to as few
  corners as it can. Where there is no way round within reach, it is drawn square.

Beside those are its **colours**: the colour of what it carries (default), or one of the theme's —
accent, sage, ochre, sky, pink, plum or slate. A run still marks a wire it went down, or stopped at,
over whatever colour it is.

Each wire keeps its own, and **Ctrl+Z** puts back the last one changed. It changes only how the wire
is drawn, never what it carries. Wires out of a [Relay](Nodes/Canvases%20and%20Relays.md#relay)
leave and arrive the way the relay faces.

## Selecting, copying and removing

- **Shift-click** boxes, or **Shift-drag** across empty canvas, to select several. **Escape** clears
  the selection.
- **Delete** or **Backspace** removes what is selected. With nothing at stake — filters, sorts,
  pieces, comments, relays — it goes at once, and **Ctrl+Z** puts it back where it was, wires and
  all. A source or feed box asks first: removing it also removes the source or feed behind it, with
  its history, unless another box still stands for it, and that cannot be undone.
- **Ctrl+C** copies what is selected — with the pieces slotted under it, whatever a selected group
  surrounds, and the wires between them — and **Ctrl+V** pastes it where the pointer is, as new
  boxes. A source or feed box pastes as another box for the *same* source or feed, as drawing one
  twice does: a copy never duplicates a feed or what it has collected. Ctrl+Z takes a paste away.
- **Ctrl+X** cuts what is selected: it fades, and stays until **Ctrl+V** moves it to where the
  pointer is — here, or in another [canvas](Nodes/Canvases%20and%20Relays.md#canvas). It moves the
  boxes themselves, with their history and the wires between them; into another canvas, the wires
  to boxes left behind go, since a canvas keeps to itself. Nothing is lost if it is never pasted.
- With several selected, the bar at the top of the canvas offers the same: **Copy**, **Cut**,
  **Paste** (once something is waiting) and **Remove**.
- An empty source box — never told which source it is — copies as an empty box of its kind.
- What was copied or cut is kept in this browser, so it can be pasted into another canvas, or after
  leaving the tab. On a Mac, use ⌘ for Ctrl. The keys leave alone a field being typed in, and text
  you have chosen.

## Moving around

- **Drag empty canvas** to pan. It has no edges.
- **Scroll** to zoom (30%–250%), keeping the point under the pointer still. Scrolling over a panel
  scrolls the panel instead.
- **Find a group** jumps to a [group](Nodes/Groups.md).

Where you were stays where it was: leave the tab, or reload, and the canvas opens at the same spot
and zoom. It is kept in this browser, so another device starts at the top left.

## Undo

**Ctrl+Z** (or **⌘Z**), or the undo button, takes back the last change — adding a box, moving or
resizing, drawing or removing a wire, or a panel edit. Up to 40 steps. Removing a box cannot be undone.

## Other buttons

- **Load a group** — add a [group](Nodes/Groups.md) somebody sent you.
- **Run log** — [what runs have been doing](The%20Run%20Log.md).

**Related:** [Sources](Nodes/Sources.md) · [Feeds](Nodes/Feeds.md) · [Triggers](Nodes/Triggers.md) ·
[Testing a Flow](Testing%20a%20Flow.md)
