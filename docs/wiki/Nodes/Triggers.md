# Triggers

A trigger says **when** a source is checked. A source with no trigger wired into it is never checked
automatically.

Wire a trigger into one or more [sources](Sources.md), or into a [Withdraw](Repositories.md) box to
say when to release a repository.

## Two kinds

| Trigger | Says | Example |
| --- | --- | --- |
| **Pulse** | Every so often, counted from the last check | every 2 hours |
| **Schedule** | At set times, as a cron expression in **UTC** | `0 9 * * 1-5` — 09:00 on weekdays |

A Pulse of `0` means every run. A source never checked before is always due.

When several triggers are wired into one source, it is checked when **any** of them is due.

## How often triggers are looked at

De-Algo wakes every **30 minutes** and checks every trigger then. So a trigger cannot fire more often
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
