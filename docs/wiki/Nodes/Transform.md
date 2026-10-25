# Transform

A **Transform** box turns what comes into it into **data**, as the piece slotted under it says. It
sits on no path: nothing goes on down a ▶ wire from it.

Wire one thing into it — **items** into its ▶ port (from a source or any box on a path), or
**data** into its `{ }` port. Wiring a second in replaces the first. What it gives out, from its
`{ }` port, can go into a [chart leaflet](Pamphlets.md#charts), a [Format](Format.md) box, or
another operation.

Items are read as rows, the same ones a source's data gives, after every box on their way: a
Filter before it has already held back what it holds back.

## Pieces

| Piece | Gives out |
| --- | --- |
| **Count** | How many came in — items, or the rows of its data — as JSON: `{"count": 8}`. |
| **Lua** | Whatever a piece of Lua you write makes of it — see [Lua](#lua) below. |
| A plugin's | Whatever its plugin's transformation makes of it, set in the piece's panel. Listed under **Plugins** in the palette. |

With no piece under it, a Transform gives out what came in, as data. Pieces apply nearest the box
first, each to what the one before gave out.

## Lua

A **Lua** piece is a transformation written by hand, for anything a Count cannot do — keep some
rows, reshape them, total them, join text, work something out:

![A Lua piece's panel under a Transform box](../images/lua.png)

```lua
-- The ten most watched, with only what a chart needs.
table.sort(data, function(a, b) return (a.views or 0) > (b.views or 0) end)
local out = {}
for i = 1, math.min(10, #data) do
  out[i] = { title = data[i].title, views = data[i].views }
end
return out
```

- `data` is what comes in: a list of rows, or one value.
- `params` are the values its flow was [activated](Triggers.md#activation-and-activate) with —
  `params.city` — or empty.
- `json.decode(text)` and `json.encode(value)` read and write JSON text.
- Whatever it `return`s is what the Transform gives out, as JSON.

Write it in the piece's panel; a Tab indents. Double-click the Transform to see, side by side, what
comes in and what the Lua makes of it. Lua it cannot read is refused when saved; Lua that fails as
it runs gives out nothing, and the editor's output says why.

It runs in the same sandbox as a [plugin](../Creating%20A%20Plugin/The%20Sandbox.md): `string`,
`table` and `math`, and nothing of the machine — no files, no network — and it is stopped if it runs
too long or uses too much memory.

What a Transform gives out is always JSON. A chart leaflet given an object holding one number, such
as a count, shows it as a large figure under the Transform's name, with the field's name beneath.
A Text box reads it as it is.

**Related:** [Format](Format.md) · [Pamphlets](Pamphlets.md)
