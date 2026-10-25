# Groups

A group is a rectangle drawn behind part of your canvas. It carries nothing; it arranges.

Drag **Group** from **Layout** in the palette, then resize it from its corner. Name it in its panel.

## What a group does

- **Moves as one.** Dragging the group moves every box inside it.
- **Locks in place.** The padlock beside its name holds it where it is. A locked group can't be
  dragged or resized: dragging across it moves the canvas instead, as dragging empty canvas does.
  The boxes inside it still move on their own. Press the padlock again to let it go.
- **Has a colour.** Paper, sage, blush, ochre or sky — the theme's own, as a
  [comment](Canvases%20and%20Relays.md#comment)'s are — chosen in its panel.
- **Folds up.** The ▾ beside its name folds the group to a bar with its name and how many boxes it
  holds; what it holds is hidden, and wires to those boxes end on the folded bar. ▸ opens it out
  again. Folding has nothing to do with the lock: a locked group folds, and a folded one stays
  wherever it is, moving its hidden boxes with it if it is dragged.
- **Is not saved as a file any more.** To hand part of your setup to someone, put it in a
  [Canvas box](Canvases%20and%20Relays.md#saving-a-canvas-as-a-file) and save that as a `.pam`
  file. A group file saved before still loads, as a group, with **Load a canvas**.

## What travels in a file

This is also what travels in a [`.pam` file](Canvases%20and%20Relays.md#saving-a-canvas-as-a-file),
which carries a whole canvas the same way.


- Sources travel as their kind, identifier and feed address. Missing ones are created, paused; a
  source whose plugin is not installed does nothing until it is.
- Feeds travel as names, and are always created new as feeds inside Pamphlets.
- Filters, sorts, marking boxes, repositories, triggers, and every augmentation, with their settings.
- Only wires with both ends inside the group.

No history and no credentials are included. Files from older versions still load.

## Updating a loaded group

A group you loaded from a group file saved before remembers it. Its panel says which file and when, and offers
**Update from file…**: choose a newer copy of that file, and the group is brought up to date.

- **Boxes the file still has are updated in place.** Their settings, names and conditions come from
  the file, but each stays the same box, so its history, channel and feed are kept. Boxes you moved
  stay where you put them.
- **Boxes the file adds are made**, where the file puts them.
- **Boxes the file no longer has are taken away.** A feed whose box goes is kept, with everything in
  it, on the Feed tab, and the update tells you which ones. An update never deletes what you've
  been reading.
- **What you added yourself stays:** boxes you put in the group, and wires to boxes outside it.
  The wires between the file's own boxes are redrawn from the file.
- **It must be the same group.** Every exported file carries an id, and a file for a different group
  is refused without changing anything; use **Load a group** to add that one alongside. A file
  exported before ids existed is matched by its name.

The browser can't reopen a file by itself, so you choose it again each time. If you export a group
you loaded, the new file keeps the same id, so copies of copies stay updatable.

## Finding one

**Find a group** lists every group and jumps to it. Useful because the canvas has no edges.

**Related:** [The Configuration Canvas](../The%20Configuration%20Canvas.md) ·
[Backup and Restore](../Backup%20and%20Restore.md)
