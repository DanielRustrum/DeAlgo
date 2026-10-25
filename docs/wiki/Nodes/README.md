# Nodes

Everything you can place on the [Configuration Canvas](../The%20Configuration%20Canvas.md).
**Boxes** are wired together; **pieces** slot under a box and change what it does.

## Boxes, in the order an item meets them

| Node | Does |
| --- | --- |
| [Trigger](Triggers.md) | Decides when the sources wired to it are checked: Pulse, Schedule — or Activation, set off by an Activate box |
| [Source](Sources.md) | Where items come from: feed addresses, newsletters, REST APIs, form submissions (Input), and the plugins' kinds |
| [Newsletter](Newsletters.md) | A source found by the newsletter's address |
| [Filter](Filter.md) | Lets some items through, holds others back |
| [Sort](Sort.md) | Puts the batch in order |
| [Tag](Tag.md) | Marks items for a Filter further on |
| [Decay](Decay.md) | Limits how long you spend on each item |
| [Expire](Expire.md) | Takes items out of a feed after a while |
| [Feed](Feeds.md) | Where items end up |
| [Deposit and Withdraw](Repositories.md) | Hold items now, release them later |
| [Activate](Triggers.md#activation-and-activate) | Ends a path: sets an Activation off, in any canvas, with values of your choosing |
| [Return](Triggers.md#activation-and-activate) | Ends an activated flow: sends what reaches it back to the Activate box |
| [Group](Groups.md) | A background for arranging and sharing boxes |
| [Canvas](Canvases%20and%20Relays.md#canvas) | A canvas of its own, opened by double-clicking it; five deep at most |
| [Relay](Canvases%20and%20Relays.md#relay) | A dot a wire passes through, to route it round other boxes |
| [Comment](Canvases%20and%20Relays.md#comment) | A note left on the canvas, in one of the theme's colours |
| [Pamphlet](Pamphlets.md) | A page of your own under the Pamphlets tab; on no path |
| [Format](Format.md) | Reshapes a source's JSON into bars for a chart leaflet; on no path |
| [Transform](Transform.md) | Turns items or data into data — a count, Lua of your own, or a plugin's; on no path |
| [Text](Text.md) | Has your AI model write from what comes in, for a Text leaflet; on no path |

## Pieces

| Node | Slots under | Does |
| --- | --- | --- |
| [Conditions](Augmentations.md) | Filter, Sort | What a Filter narrows by, and what a Sort orders by |
| [Timer, Reset, Alive](Reading%20Windows.md) | Feed | When a feed can be read |
| [Timer, Lock](Decay.md) | Decay | Time per item, and whether it can be paused |
| [Timer](Expire.md) | Expire | How long an item stays |
| [Count](Transform.md#pieces) | Transform | How many came in, as one number |
| [Lua](Transform.md#lua) | Transform | A transformation written by hand |
| [Inputs](Pamphlets.md#forms) | Form leaflet | A form's fields: text, long text, number, date, choice, checkbox |
| [Aggregation](Aggregation.md) | Filter, Sort, Expire | Your own algorithm, at work |
| [Leaflets](Pamphlets.md#leaflets) | Pamphlet, or beside another leaflet | The blocks of a pamphlet's page: feeds, words, links, charts, maps, [videos](Pamphlets.md#videos) and [forms](Pamphlets.md#forms) |

All pieces are covered in [Augmentations](Augmentations.md).
