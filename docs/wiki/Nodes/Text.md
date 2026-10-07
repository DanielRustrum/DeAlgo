# Text

A **Text** box has a language model write from what comes into it — a morning briefing, a summary,
what stands out — and puts what it wrote on a [pamphlet](Pamphlets.md) through a **Text leaflet**.
It sits on no path.

Wire **one** thing in: items into its ▶ port (from a source or any box on a path), or data into its
`{ }` port. Wire its sheet port, on the right, into a Text leaflet's sheet port. The leaflet then shows
what the box wrote, under the leaflet's heading or the box's name, with when it was written.

The model is your own choice, under [Settings → AI model](../Settings.md#ai-model).

## Its panel

| Setting | Says |
| --- | --- |
| **What to write** | Your instructions to the model: what to write, how long, in what voice. |
| **Items it reads** | How many of what comes in it sends, from the first — up to 100. Each item's text is cut to its first 600 characters, and the model is told how many there were. |
| **Writes again** | Only when you press **Write now**, or by itself every hour or every day, on a run. |

**Write now** writes straight away; a model can take a little while. The panel shows the start of
what it last wrote. If a try fails — no model chosen, nothing has come in, the key was refused — it
says why, and the leaflet keeps what it wrote last time.

A page never waits on the model: opening a pamphlet shows what was last written, and costs nothing.

## What the model is told

Beyond your instructions, every model is told to write only from the items it is given — no
invented items, facts, numbers or links — and in plain prose: paragraphs, `## ` subheadings and
`- ` lists, which the page sets as copy.

**Related:** [Pamphlets](Pamphlets.md) · [Transform](Transform.md) · [Format](Format.md)
