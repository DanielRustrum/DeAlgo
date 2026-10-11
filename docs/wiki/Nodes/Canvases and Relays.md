# Canvases and Relays

Two boxes under **Layout** in the palette that change nothing about what is collected: they arrange
the canvas. A [group](Groups.md) is the third.

## Canvas

A **Canvas** box is a canvas of its own: a room for part of your setup. **Double-click** it, or press
**Open** in its panel, and the canvas shows what is inside it. A trail across the top —
**Configuration › Ingest › YouTube** — says where you are; press any step of it to go back out.

- **It keeps to itself.** A box inside is wired only to boxes beside it, in the same canvas, and a
  piece slots only under a box in the same canvas. Nothing is wired to the Canvas box itself.
- **Everything inside runs.** A source inside is polled, its paths fill their feeds, and a chart
  inside a pamphlet inside it is drawn, exactly as if it were at the top.
- **Five deep.** A canvas can hold canvases, and they can hold canvases, five deep below the top.
- **Each remembers its view.** Where you were in each canvas, and which canvas was open, is kept in
  this browser: leave the tab or reload, and it opens where you left it.
- **Taken away, it takes everything inside it** — sources and feeds included, as removing each of
  them would. It asks first, unless it is empty.

The box says how many boxes are inside it, and is drawn as a stack of sheets: there is more
underneath.

A Canvas box in a [group](Groups.md) travels in the group's file as an empty canvas: what is inside it
does not go with it yet.

## Relay

A **Relay** is a dot a wire passes through, so a wire can be routed round other boxes instead of
under them. Wire anything into it, then wire on from it: it passes on what comes in, unchanged, to as
many boxes as you like.

- **One wire in, of any kind** — items, data, a feed onto a page, or a trigger's signal. A second
  wire in replaces the first. Its dot is dashed until something is wired in.
- **It allows what its start allows.** What comes out of a relay can go wherever a wire straight from
  the box at the start of it could go — and nowhere else. A trigger through a relay still only polls
  a source.
- **It changes nothing.** Everything that reads the canvas — what a run collects, what a chart draws,
  which feed a leaflet shows, when a trigger polls — sees straight through a relay, as if the wire
  went from end to end. Relays can follow relays.
- Its two ports show when you reach for it; at rest it is just a dot on the wire.

**Related:** [Groups](Groups.md) · [The Configuration Canvas](../The%20Configuration%20Canvas.md)
