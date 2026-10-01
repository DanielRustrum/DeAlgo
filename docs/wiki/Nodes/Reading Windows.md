# Reading Windows

Limit when a feed may be read, by slotting augmentations under its box.

| Piece | Means |
| --- | --- |
| **Timer** | How long you get once you start reading. Counted from when you open the Feed page. |
| **Reset** | When you get another session — a cron expression, in UTC. |
| **Alive** | The hours of the day the feed may be read, `HH:MM` to `HH:MM`, in UTC. |

## Combining them

- **Timer + Reset** — e.g. 90 minutes, renewed every midnight.
- **Timer alone** — one session, ever.
- **Reset alone** — 30 minutes each time it comes round.
- **Alive** narrows whatever else is set: a session with time left is still shut outside its hours.
- Several **Resets** are several chances to read. Several **Alive** pieces are several allowed
  stretches; any one is enough.
- With several Timers, the one nearest the feed wins.
- **Alive** from `00:00` to `00:00` allows the whole day; that is its default.

## A shut feed

The Feed page shows it as shut — never hidden — with the rule you set and when it opens again.

Your session starts when you open the Feed page. A page refreshing itself after a run does not
start one.

## Limits

- Times are **UTC**, not your local time.
- [Focus Mode](../Focus%20Mode.md) does not yet respect reading windows.

**Related:** [Augmentations](Augmentations.md) · [The Feed Page](../The%20Feed%20Page.md) ·
[Triggers](Triggers.md)
