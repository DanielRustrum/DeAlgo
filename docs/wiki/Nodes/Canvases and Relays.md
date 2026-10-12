# Canvases, Relays and Comments

Three boxes under **Layout** in the palette that change nothing about what is collected: they arrange
the canvas, and say what it is for. A [group](Groups.md) is the fourth.

## Canvas

A **Canvas** box is a canvas of its own: a room for part of your setup. **Double-click** it, or press
**Open** in its panel, and the canvas shows what is inside it. A trail across the top —
**Configuration › Ingest › YouTube** — says where you are; press any step of it to go back out.

- **It keeps to itself.** A box inside is wired only to boxes beside it, in the same canvas, and a
  piece slots only under a box in the same canvas. Nothing is wired to the Canvas box itself.
- **Everything inside runs** — unless it is [frozen](#freezing-a-canvas). A source inside is
  polled, its paths fill their feeds, and a chart inside a pamphlet inside it is drawn, exactly as
  if it were at the top.
- **Five deep.** A canvas can hold canvases, and they can hold canvases, five deep below the top.
- **Each remembers its view.** Where you were in each canvas, and which canvas was open, is kept in
  this browser: leave the tab or reload, and it opens where you left it.
- **Taken away, it takes everything inside it** — sources and feeds included, as removing each of
  them would. It asks first, unless it is empty.

The box says how many boxes are inside it, and is drawn as a stack of sheets: there is more
underneath. **Resize it** from its corner, as a group or a comment is, and its words grow and shrink with it
— by whichever of its width and height changed least, so they still fit (from three-quarters of
their usual size up to four times it). It keeps its size in copies and files.

### Freezing a canvas

Press **Freeze** in a Canvas box's panel and nothing inside it runs, however many canvases deep:
no trigger fires (Run now and Backfill refuse), no source is polled for it, no item goes through
its boxes or lands in a feed inside it, no Withdraw pulls and no Text box writes. A source whose
only trigger is inside is left alone, as if nothing were wired to it.

Everything is still there to change. The box is **snowed in and iced over**: a low layer of
snow lies along its top and its bottom, following its rounded corners, with short drips and a pale
blue underside; a fringe of icicles hangs from the top snow into the box, longer ones from the
bottom snow below it, and frost fades down the box — with a **❄ Frozen** badge, sized to the box however it was resized, in the theme's
[Frost](../Theming.md#colours) colours. Inside, the view itself is iced in its two top corners and has drifts of snow in its bottom two, the boxes are drawn muted, and about a
third of them wear a touch of the same ice — a few small icicles under part of the bottom edge of
the box, or of the last piece slotted under it, the same boxes every time — and the trail
says *Frozen: nothing here runs*. Each box keeps its own **Active** switch, so
**Thaw** puts everything back exactly as it was — a box you switched off stays off.

A frozen canvas copied, or saved as a file, stays frozen. A box copied out of one runs where it is
pasted.

### Which plugins a canvas offers

With plugins installed, a Canvas box's panel has a **Plugins** tab: a switch for each plugin that
puts boxes in the palette. Switch one off and, inside this canvas, the palette no longer shows that
plugin's sources or the conditions it adds — and one is refused there however it arrives: dropped
in, pasted, moved in by a cut, loaded from a file, or an empty source box pointed at one. The
change is saved as soon as you flip the switch. **Offer every plugin** goes back to all of them,
including any installed later.

- **A canvas inside offers no more than the canvases around it.** A plugin one leaves out shows
  greyed on the Plugins tab of every canvas inside it, *left out by a canvas around this one*.
- **Boxes already there stay, and run.** It decides what can be added, not what is already drawn.
- **The app's own boxes are always offered** — feeds, filters, triggers, feed addresses,
  newsletters, REST APIs, leaflets and the rest.
- A canvas copied, or saved as a file, keeps which plugins it offers.

### Saving a canvas as a file

**Save as file** in a Canvas box's panel saves it, and everything inside it, as a **`.pam`** file to
hand somebody else: each box with its settings, the pieces slotted under it, comments, relays and
groups as they look, the canvases inside it and everything inside those, and the wires between —
each drawn the way it was. See [what travels in a file](Groups.md#what-travels-in-a-file); no history
and no credentials go with it.

**Load a canvas** on the canvas (the arrow into a tray) takes a `.pam` file in as a new Canvas box,
with all of that inside, in whichever canvas you have open. Nothing already here is changed. It is
refused if it would take canvases more than five deep where it is loaded.

- **It comes in [frozen](#freezing-a-canvas)**, and the sources it names paused: somebody else's
  setup does nothing until you have looked it over and pressed **Thaw**.
- **Plugins it needs that are not here are asked about first.** The file names the plugins its boxes
  are from, and the repository each was installed from. If any are missing, nothing is loaded yet:
  the dialog lists them, each with **Install…**, which opens Admin → Plugins in a new tab to agree to
  what it asks for, as installing any plugin does. Then press **Load again** — or **Load without
  them**, and their boxes come in but do nothing until the plugin is here. A plugin switched off here
  is said as that; one installed from a file rather than a repository has nowhere to be fetched
  from, so ask whoever sent the file. Only an admin installs plugins; anybody else is told to ask
  one.
- Each source keeps its kind — a subreddit comes in as a subreddit.

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
- **Any two sides.** Its panel has a drawing of it: choose **Placing the way in** or **Placing the
  way out**, then press one of its four sides. Put one on the other's side and the two swap, so
  there is always one way in and one way out. A wire can come in at the bottom and leave on the
  left — turning any corner.
- **A colour.** Default grey, or one of the theme's: accent, sage, ochre, sky, pink, plum or slate.
- Its two ports show when you reach for it; at rest it is just a dot on the wire.

## Comment

A **Comment** is a note left on the canvas, for whoever reads it next — you, later. It is wired to
nothing and changes nothing.

- **Double-click it to write in it**, where it is. Click away, or press Ctrl+Enter, to keep what you
  wrote; Esc puts back what was there. Its panel has the same words, and its colour.
- **Written in Markdown**, and shown the way it reads: `#` headings, `**bold**`, `*italic*`,
  `~~struck~~`, `` `code` `` and fenced code blocks, `[links](https://…)`, `-` and `1.` lists,
  `- [ ]` and `- [x]` task lists, `>` quotes and `---` rules. Links open in a new tab. While you
  write in it you see the words as typed. Nothing in a comment can run as script — not even one in
  a file somebody sent — and a link only goes to a web or mail address.
- **Five colours**, all the theme's own: paper, sage, blush, ochre and sky. They follow the theme,
  light and dark.
- **Resize it** from its corner, as a group is resized.
- It sits under the boxes around it, so a note never hides what it is about. It travels with a
  [group](Groups.md) it is in — in the group's file too — and can be left in any canvas.

**Related:** [Groups](Groups.md) · [The Configuration Canvas](../The%20Configuration%20Canvas.md)
