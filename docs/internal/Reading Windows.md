# Reading Windows

Pieces under a Feed box decide **when the feed may be read** — the opposite of a trigger, which
decides when to fetch. `graph.window_state(pieces, now)` is the whole algorithm.

## Pieces

| Piece | Field | Meaning |
| --- | --- | --- |
| Timer | `duration_minutes` | Length of one sitting, counted from the first visit |
| Reset | `cron` | When a spent sitting re-arms |
| Alive | `alive_from`, `alive_to` (`HH:MM`, UTC) | Hours the feed may open at all |

`consumption()` maps each playlist to the enabled pieces under its feed boxes.

## `window_state`

```
no pieces                         → open
some Alive, none allows now       → shut, opens_at = next Alive start
no Timer and no Reset             → open
window = first Timer's minutes, else 30
anchor = first Timer, else first Reset          (holds last_fired_at = sitting start)
anchor never fired                → open, start a sitting
now − start < window              → open (in a sitting)
no Reset                          → shut for good (one sitting only)
any Reset fired in (start, now]   → open, start a new sitting
else                              → shut, opens_at = soonest next Reset
```

- **Nearest wins.** Pieces arrive nearest-first, so the first Timer is the one closest to the box.
- **Several Resets or Alives** are alternatives: any one is enough.
- **Alive** wraps midnight when `from > to`; `from == to` means all day.
- **The sitting starts on the first visit**, not at a clock time. "90 minutes a day" begins when the
  reader sits down. (An earlier version measured from the Unix epoch, which put every window at
  midnight UTC.)

## Reading without starting a sitting

| Call | Starts a sitting? | Used by |
| --- | --- | --- |
| `is_open(pieces, now)` | No | Canvas, feed list badges |
| `window_state` + `begin_sitting` | Yes | Opening the feed page |

`begin_sitting` stamps `last_fired_at` on the anchor only when the feed actually opens, so a sitting
is never spent while something else holds the feed shut.

## Not covered

Focus mode does not consult reading windows. See [Known Issues](Known%20Issues.md).
