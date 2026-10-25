# Content View

Go through unwatched items one after another, without choosing what is next.

![Content view showing a recipe, laid out by its source's plugin, with a form to rate it](images/content.png)

Start it from **Content view ▶** in [List view](List%20View.md) (every feed), from a feed's section (that feed), or by
clicking a card (starting there, in that feed's order).

## How it advances

- A **video** from a source whose plugin gives it a player plays full width and moves on when it
  ends. A video from a source with no player is shown like an article, with a link to watch it there.
- A **post** or **article** is laid out as its images and text. Click an image to open it full size,
  or **Open it on …** to read it at its source.
- A source's plugin may **lay its items out itself** — pictures, players, tables, its own styling,
  even a form you fill in right there, which the plugin answers. What it draws is made safe first:
  only a fixed set of plain components, web addresses only, and its styles reach nothing outside the
  item. See [Creating A Plugin › Sources](Creating%20A%20Plugin/Sources.md#view-item-settings-act-and-style).
- **Done · next** marks the item watched and moves on.
- **Skip** moves on without marking it. Skipped items come back next sitting.

An item that will not play (private, deleted, embedding disabled) is skipped automatically.

## Timed items

Nothing is on a clock unless you asked for it. Put a [Decay](Nodes/Decay.md) box on an item's path and a
post or article gets a countdown, and moves on by itself when it runs out. Click the timer to hold it.
Add a **Lock** under the Decay box and the countdown cannot be held.

Videos are never timed: they always play to the end.

## What it remembers

For [your algorithm](Nodes/Aggregation.md), Content view remembers how each item went: how long it was
open, how far into a video you got, how often you paused and played again, and whether you opened it
by clicking its card or skipped it. Nothing else, and nothing leaves this machine. Switch it off under
Settings → AI model.

## Notes

- Each step asks the server for the next item, so a tab left open overnight never shows something
  you already watched or removed.
- An item in two feeds is queued once.
- [Reading windows](Nodes/Reading%20Windows.md) do **not** apply here yet: a feed List view shows as
  shut still plays through Content view.
- A player is its plugin's: a frame from the service's own site, kept apart from Pamphlets's page, and
  told only to play, pause or stop. No player's script is loaded into Pamphlets. If the player never
  answers, the page says so and offers **Reload**; **Done · next** always works.
- Its address is `/focus`; the old `/watch` address still redirects here.

**Related:** [List View](List%20View.md) · [Decay](Nodes/Decay.md) · [Watched Items](Watched%20Items.md)
