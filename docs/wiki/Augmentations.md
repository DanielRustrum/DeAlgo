# Augmentations

An augmentation is a piece that slots under a box and changes what that box does. It sits on no
path and has no wires.

In the palette, augmentation rows wear a green **tab** icon, and pills under the description name the
boxes each one fits.

| Augmentation | Fits under | Does |
| --- | --- | --- |
| **Timer** | Feed, Decay, Expire | An amount of time. Its meaning comes from the box — see below. |
| **Reset** | Feed | When reading time comes back. See [Reading Windows](Reading%20Windows.md). |
| **Alive** | Feed | The hours a feed may be read. See [Reading Windows](Reading%20Windows.md). |
| **Lock** | Decay | Makes a Decay countdown impossible to pause. See [Decay](Decay.md). |
| **Title has**, **Title lacks**, **Longer than**, **Shorter than**, **Carrying**, **At most** | Filter | A condition. See [Filter](Filter.md). |
| **Order** | Sort | What to order by. See [Sort](Sort.md). |
| Plugin conditions | Filter | See [Filter](Filter.md). |
| Plugin orderings | Sort | See [Sort](Sort.md). |

A **Timer** means:

- under a **Feed** — how long a reading session lasts;
- under a **Decay** — how long you get with each item;
- under an **Expire** — how long an item stays in the feed.

## Slotting one in

Drag it from the palette towards the bottom edge of a box. Only boxes it fits light up, and a dashed
slot shows where it will land. Drop it there.

Dropped anywhere else, it lies loose on the canvas; drag it onto a box later. Dropping on a box it
does not fit is refused with a reason.

A box with something slotted in has a notch on its free bottom edge; a loose piece has a tab on top.

## Chains

Pieces stack: a piece can slot under another piece. The whole chain belongs to the box at the top.

Dragging any piece moves the whole assembly. Taking a piece out of the middle closes the chain up
behind it.

## Taking one out

Open the piece and press **Take it out**. It stays on the canvas, slotted into nothing, and does
nothing until you slot it in again. **Remove** deletes it.

Removing a box removes everything slotted under it.

**Related:** [Filter](Filter.md) · [Sort](Sort.md) · [Reading Windows](Reading%20Windows.md) ·
[Decay](Decay.md) · [Expire](Expire.md)
