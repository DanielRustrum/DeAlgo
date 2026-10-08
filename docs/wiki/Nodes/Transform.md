# Transform

A **Transform** box turns what comes into it into **data**, as the piece slotted under it says. It
sits on no path: nothing goes on down a ▶ wire from it.

Wire one thing into it — **items** into its ▶ port (from a source or any box on a path), or
**data** into its `{ }` port. Wiring a second in replaces the first. What it gives out, from its
`{ }` port, can go into a [Chart leaflet](Pamphlets.md#leaflets), a [Format](Format.md) box, or
another operation.

Items are read as rows, the same ones a source's data gives, after every box on their way: a
Filter before it has already held back what it holds back.

## Pieces

| Piece | Gives out |
| --- | --- |
| **Count** | How many came in — items, or the rows of its data — as JSON: `{"count": 8}`. |

With no piece under it, a Transform gives out what came in, as data. Pieces apply nearest the box
first.

What a Transform gives out is always JSON. A Chart leaflet given an object holding one number, such
as a count, shows it as a large figure under the Transform's name, with the field's name beneath.
A Text box reads it as it is.

**Related:** [Format](Format.md) · [Pamphlets](Pamphlets.md)
