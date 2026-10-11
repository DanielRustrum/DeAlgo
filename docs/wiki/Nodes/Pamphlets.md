# Pamphlets

A **Pamphlet** box is a page of your own, shown under the **Pamphlets** tab. What is on the page is
whatever **leaflets** you slot under the box, laid out the way they sit on the canvas.

## Laying out a page

Drag a **Pamphlet** box out of the palette (under **Pamphlets**), then drag leaflets onto it:

- **Below** the box or another leaflet: the next thing down that column.
- **Beside** a leaflet (its right edge): the next column to its right.

A dashed slot shows where a leaflet will land; a solid line means it goes in between two that are
already there. You can go in between anywhere: under the pamphlet's title and above its first
leaflet, between two stacked leaflets, between two side by side, or along the left edge of the
first leaflet in a row to go in front of it.

On the canvas the box is a small picture of its page: the leaflets sit inside it as cards, in their
columns. A small green joint shows what each one hangs from — the one above it, or the one to its
left — and a dashed notch marks each free edge where another could go.

## Moving leaflets

Drag a leaflet on its own to move it: drop it on any edge of the same or another pamphlet, including
between two, and the rest of the page closes up behind it. Drag it off into open canvas and it comes
off the page, lying where you let go. Dragging the Pamphlet box moves the whole page.

So a Text leaflet under the box, with two Feed leaflets side by side under that, is a heading
across the page over two columns. A column can split into columns again, as deep as you like. On a
phone, columns stack in the order they read, left to right.

Taking a leaflet off closes the gap: what was below it moves up, and what was beside it stays
beside.

## Leaflets

| Leaflet | Shows | Set in its panel |
| --- | --- | --- |
| **Feed** | The first few unwatched items of the feed wired into it, as stories, in that feed's own order — or the feed as one tile: a small stack of papers, its newest item on the front page and a sheet behind for every few more waiting | Shows as (stories or a tile), how many (up to 60), a heading |
| **Charts** | A leaflet for each kind of chart — see [Charts](#charts) below — showing the data wired into it, or, with nothing wired in, watched each day, arrived each day, filtered out each day, what each feed holds, or the counts | A heading; with data wired in, the rest in its editor; without, which built-in chart and how many days (2–90) |
| **Text** | A heading and your own words. A blank line starts a new paragraph — or, with a [Text](Text.md) box wired in, what its model wrote | Heading, words |
| **Link** | A line to turn to: Focus on the feed wired in (or everything), open it, or go to an address | Where it goes, what it says |

## Wiring a feed in

A Feed box has a second port on its right, marked with a **sheet of print**. Wire it into a Feed or
Link leaflet's port (the same sheet, on the leaflet's left) to say which feed that leaflet shows.
These wires are dashed and green: they carry a feed onto a page, not items down a path, and change
nothing about what is collected. A leaflet shows one feed; wiring a second in replaces the first.
A Link leaflet set to Focus with no feed wired in goes through everything.

A Feed leaflet follows the feed's [reading windows](Reading%20Windows.md): a shut feed shows as shut.
Opening a pamphlet does **not** start a reading window's sitting; opening the feed itself does.

## Charts

Each kind of chart is a leaflet of its own, under **Charts** in the canvas's palette. The drawn ones
are drawn by [Chart.js](https://www.chartjs.org/), which comes with Pamphlets — nothing is fetched
from elsewhere — in the [theme's chart colours](../Theming.md#colours).

| Leaflet | Shows | How it can be drawn |
| --- | --- | --- |
| **Bar chart** | Amounts side by side: a bar for each | Up the page or across it; series side by side or stacked |
| **Line chart** | Change over time: a line for each series | Lines or filled areas; series each on their own or stacked; straight or smooth |
| **Pie chart** | Parts of a whole: the largest five, and Other | A pie or a doughnut |
| **Radar chart** | A few things measured the same ways, as shapes round a centre | Filled or lines |
| **Polar area chart** | Parts of a whole, as wedges reaching as far as their size | — |
| **Scatter chart** | A dot for each row, placed by two of its numbers (or a date along the bottom) | — |
| **Bubble chart** | A dot for each row by two numbers, as big as a third | — |
| **Number leaflet** | One number, set large: a count, a total, an average | — |
| **Table leaflet** | The numbers as a table, a row for each | — |

A chart leaflet has a `{ }` port on its left. Wire data into it from a source box, an operation, a
Deposit or Withdraw, a [Transform](Transform.md) or a [Format](Format.md) box. Then double-click it
for the [editor](../The%20Configuration%20Canvas.md#the-editor): the wired data on the left, how to
organise it in the middle, and the chart as the page will show it on the right, redrawn as you
change. The settings are worded for the chart, and a sentence above them says what it will show —
"A line: one for each **published (by day)**, as high as **the total of views**, split by
**source**."

| Setting | Says |
| --- | --- |
| **One bar (slice, spoke, row…) for each** | The field that says what each one is. **Try:** offers fields from the data that make a good chart — words that repeat, like a source or a status, and dates. A date is grouped by day, week, month, weekday or hour, or each moment is its own point. A list gives a point for each thing in it. Not for one number. |
| **Bar length (height, slice size…) is** | How many rows there are, or the total, average, smallest, largest or last value of a number field. |
| **Split by** *(optional)* | A field whose every value gets its own colour, line, band or shape, with a legend. The five largest are named and the rest are **Other**. Not for a pie, a polar area or one number. |
| **Order, how many, where the rows are** | Folded away, since they are usually right: the order, at most how many (up to 60), and where the list is in the data — blank finds it. |

A Scatter or Bubble chart asks instead what goes **along the bottom** (a number or a date), **up the
side** (a number), a bubble's **size**, and optionally what to **colour by** — up to 500 rows.

Until a field is chosen, the chart shows a guess — the first of **Try:**, or for a scatter the
likeliest two numbers — and says so. Drag a field from the input onto a setting to use it. **Save**
keeps it all; ✕ or Esc leaves it as it was.

Chart leaflets from before each chart had its own were turned into the chart each was drawing:
columns and bars into a Bar chart, a stacked area into a filled, stacked Line chart, and so on.

A Format box wired in has already said which rows, labels and numbers there are, so its chart
offers only how it is drawn. A Transform giving one number shows it large, whichever chart it is.

Every chart has one scale. Each mark shows its number on hover or focus, and two series or more
always have a legend. To show every number, draw it as a **Table**. Counted or added up, a point with nothing in
it is zero; averaged, it is a gap in the line. Built-in charts count in UTC days.

A switched-off leaflet is left off the page.

## The page

A pamphlet is set like a newspaper: its name as the masthead, the date and how many stories are
inside on the dateline, then its leaflets in columns divided by thin rules. A Feed leaflet's first
item leads, with its picture across the column; the rest follow as headlines with a byline and a
small picture. A Text leaflet's heading is a headline, and its words open with a drop cap. Click a
story to read it in Focus mode.

## The Pamphlets tab

The tab lists every pamphlet. On a pamphlet's page, **☆ Make it the front page** on the dateline
makes it the **default**: the app opens on it — it is the page at the app's bare address, and what an
installed app opens to. The Pamphlets tab always lists them all. The dateline then says
**★ The front page**; press it again to go back to the list. With no default chosen, the bare
address goes to the list. The full list is always one click away through **Pamphlets** at the top
of the page.

Pamphlets travel in [groups](Groups.md) like any other box. A Feed leaflet pointing at a feed in
the same group stays wired to the loaded copy of that feed.

**Related:** [Feeds](Feeds.md) · [Augmentations](Augmentations.md) · [The Feed Page](../The%20Feed%20Page.md)
