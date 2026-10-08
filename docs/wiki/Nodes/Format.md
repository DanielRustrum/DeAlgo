# Format

A **Format** box reshapes raw JSON into the bars a [Chart leaflet](Pamphlets.md#leaflets) draws. It
sits on no path and changes nothing about what is collected.

A Chart leaflet can also organise data itself, with series, lines and pies — see
[Charting data](Pamphlets.md#charting-data). A Format box is for shaping it once and drawing the same
bars in more than one place.

Wire it **from** a source box — straight, or through operation boxes — and **into** a Chart
leaflet. Its ports, and the dotted ochre wires between them, are marked with braces `{ }`: they
carry JSON, not items.

## Through the operations

Every operation box has a `{ }` input and output beside its ▶ ones, and does to data what it does to
items:

| Box | Does to the rows |
| --- | --- |
| **Filter** | Keeps the rows its conditions let through: title has/lacks (on `title`), longer/shorter than (on `duration`, in seconds), has/lacks tag (on `tags`), at most. |
| **Sort** | Orders them by its Order: `published`, `duration`, `views`, `likes` or `title`. Rows without that field go last. |
| **Tag** | Adds its tag to each row's `tags`. |
| **Expire** | Drops rows published longer ago than its Timer. |
| **Decay** | Passes them on as they are. |

A REST answer that is not itself a list becomes the list of rows found in it, so a Format box after
an operation finds its rows at the top. Fields are found where APIs usually put them, as a REST
source finds them: `name` for a title, `data.title` inside a wrapper, and so on. A box that is
switched off passes no data on.

**Deposit** and **Withdraw** boxes have a `{ }` output too: what is waiting in their repository, as
the same rows a media source gives.

Each box takes one data wire in; a second replaces it.

## What comes in

- From a [REST API](REST%20API.md) source: the endpoint's last whole answer, kept each time the source
  is checked (up to 2 MB). Pressing **Try** before it has been checked reads it once.
- From any other source (YouTube, Reddit, RSS, …): its newest 1,000 items as JSON, each with `id`,
  `title`, `link`, `kind`, `source`, `published`, `arrived`, `duration` (seconds), `views`, `likes`,
  `tags`, `status`, `watched` (true or false) and `watched_at`.

One source per box: wiring a second one in replaces the first.

## Settings

| Setting | Says |
| --- | --- |
| **Rows** | Where the list is, as a path like `data.children`. Blank finds it, the way a REST source does. |
| **Label each bar by** | A path in each row, like `data.author` or `published`. A list (such as `tags`) gives a bar for each thing in it. |
| **Group it** | For a date: by day, week, month, weekday or hour of day. |
| **Combine rows** | What rows with the same label become: a count, or the sum, average, smallest, largest or last of **The number**. |
| **The number** | A path to a number in each row. Not needed to count. Numbers written as text are read; `true` counts as 1. |
| **Order** | Biggest or smallest first, by label (dates in date order), or as they come. |
| **How many bars** | Up to 60. |
| **Draw as** | Columns, rows, or columns for dates and rows otherwise. |

Paths are dots between steps and numbers for a place in a list: `items.0.price`.

**Try** shows how many rows it found and where, the fields in them — press one to put it in whichever
path field you were last in — and the bars it would give, without saving anything.

## Examples

- Posts per day from a source: label `published`, group **by day**, combine **count**.
- Minutes watched per channel: label `source`, number `duration`, combine **add up**, from a source's
  items — or which tags turn up most: label `tags`, combine **count**.
- Score by author from a Reddit-style API: rows `data.children`, label `data.author`, number
  `data.score`, combine **add up**.

**Related:** [Pamphlets](Pamphlets.md) · [REST API](REST%20API.md)
