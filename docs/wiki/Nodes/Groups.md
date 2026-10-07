# Groups

A group is a rectangle drawn behind part of your canvas. It carries nothing; it arranges.

Drag **Group** from **Layout** in the palette, then resize it from its corner. Name it in its panel.

## What a group does

- **Moves as one.** Dragging the group moves every box inside it.
- **Locks in place.** The padlock beside its name holds it where it is. A locked group can't be
  dragged or resized: dragging across it moves the canvas instead, as dragging empty canvas does.
  The boxes inside it still move on their own. Press the padlock again to let it go.
- **Exports.** **Export** in its panel saves the boxes inside, their pieces and the wires between them
  as a file you can give to someone.
- **Loads.** **Load a group** on the canvas adds one somebody sent you, beside what you have. Nothing
  existing is changed.

## What travels in a file

- Sources travel as their identifiers. Missing ones are created, paused. **Only YouTube channels
  import correctly for now**: a Reddit, RSS or newsletter source arrives without its kind or
  feed address, so re-add those by hand.
- Feeds travel as names, and are always created new as feeds inside Pamphlets.
- Filters, sorts, marking boxes, repositories, triggers, and every augmentation, with their settings.
- Only wires with both ends inside the group.

No history and no credentials are included. Files from older versions still load.

## Updating a loaded group

A group you loaded from a file remembers it. Its panel says which file and when, and offers
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
