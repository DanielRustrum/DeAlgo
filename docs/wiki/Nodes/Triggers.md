# Triggers

A trigger says **when** a source is checked. A source with no trigger wired into it is never checked
automatically.

Wire a trigger into one or more [sources](Sources.md), or into a [Withdraw](Repositories.md) box to
say when to release a repository.

## Three kinds

| Trigger | Says | Example |
| --- | --- | --- |
| **Pulse** | Every so often, counted from the last check | every 2 hours |
| **Schedule** | At set times, as a cron expression in **UTC** | `0 9 * * 1-5` — 09:00 on weekdays |
| **Activation** | When an [Activate](#activation-and-activate) box sets it off — one flow starting another | with `city` = “Tucson” |

A Pulse of `0` means every run. A source never checked before is always due.

When several triggers are wired into one source, it is checked when **any** of them is due.

## Activation and Activate

An **Activation** trigger has no clock. It starts its flow — the sources and Withdraw boxes it is
wired to — only when an **Activate** box sets it off, or when you press **Run now** on it.

- **It takes parameters.** In its panel, give each a name — letters, digits and `_` — and a
  default. **Add a parameter** adds a row; ✕ takes one away. The panel also says what it was last
  set off with.
- **Its flow reads them** as `{{ params.name }}`: in a [REST API](REST%20API.md) source's address
  and header, and in a [Text](Text.md) box's instructions. A Text box in the flow writes as soon as
  the flow is set off, whatever its own timing says.
- **Its `{ }` port gives them out** as one row of data — `city`, `days` — for a Format box, a
  Transform, a Text box or a chart.

An **Activate** box is under **Operations**. It ends a path, as a feed or a Deposit does, and
takes items (▶) and data (`{ }`).

- **It sets off any Activation**, in any canvas — that is how one canvas can start another. Pick
  one under **Sets off**; the Activation's parameters appear below it.
- **Fill each parameter** with words, `{{ fields }}` of the first item to reach it — `{{ title }}`,
  `{{ link }}`, `{{ words }}`, `{{ source }}`, `{{ tags }}` — the data wired into its `{ }` port as
  `{{ data… }}`, or the values of the Activation that started *its* flow as `{{ params… }}`. A
  parameter left empty takes its default.
- **Once per run.** When a run gets anything down a path to it — something that arrived in that
  run and got through the filters on the way — it sets the Activation off once, with the first such
  item's fields, and the Activation's flow runs straight after.
- **Five deep.** Flows that set each other off stop after five in a row.

A **Return** box, under **Operations** beside Activate, ends the flow an Activation starts and sends
something back, the way a function returns a value:

- Wire items (▶) or data (`{ }`) into it, anywhere in the Activation's flow.
- At the end of that flow's run, what reached it goes back to the **Activate box that set the flow
  off** — the last one to, if several can. Data goes back as it is; items, as rows.
- It comes out of that Activate box's own `{ }` port, for a Format box, a Transform, a Text box or a
  chart in the flow that asked. The Activate box's panel says when something last came back, and
  what.
- An Activation set off by hand, with **Run now**, has nobody to send back to.
- An Activation that is switched off, or in a [frozen canvas](Canvases%20and%20Relays.md#freezing-a-canvas),
  is not set off. Copies and `.pam` files keep its parameters, and an Activate box copied with its
  Activation points at the copy.

## How often triggers are looked at

Pamphlets wakes every **30 minutes** and checks every trigger then. So a trigger cannot fire more often
than that: a Pulse of 5 minutes behaves like 30, and a Schedule at 09:00 fires at the first wake-up at
or after 09:00 — up to 30 minutes late.

## Buttons on a trigger

- **Run now** — check what this trigger is wired to, now, whatever its schedule says.
- **Backfill** — the same, but run through the latest N items of each source (blank: as far back as
  each feed lists). Brings back what an earlier run passed over as too old.
- **Test** — show what a run would do, without doing it. See [Testing a Flow](../Testing%20a%20Flow.md).

A run started from a trigger fills only the paths out of the boxes that trigger is wired to. If one
source has two boxes with different triggers, each trigger fills only its own box's paths.

While a run is going, the canvas lights the boxes and wires it is working through.

## Cron in brief

Five fields: minute, hour, day of month, month, day of week. Day of week counts from Sunday = 0, as
in standard cron.

| Expression | Means (UTC) |
| --- | --- |
| `0 9 * * *` | 09:00 every day (the default) |
| `30 7 * * 1-5` | 07:30 Monday to Friday |
| `0 */6 * * *` | Every 6 hours |
| `0 18 * * 0` | 18:00 on Sundays |

**Related:** [Sources](Sources.md) · [Repositories](Repositories.md) · [The Run Log](../The%20Run%20Log.md)
