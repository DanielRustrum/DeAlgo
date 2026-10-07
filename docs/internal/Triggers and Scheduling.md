# Triggers and Scheduling

Two clocks: the **heartbeat** decides when Pamphlets looks; **trigger boxes** decide what is due
when it does.

## The heartbeat — `scheduler.py`

- An APScheduler `BackgroundScheduler` in UTC with one job, `pamphlets-sync`, running
  `run_for_everyone("scheduled")`.
- Interval: the implicit owner's `Settings.poll_interval_minutes` (default 30). `max_instances=1`,
  `coalesce=True`, `misfire_grace_time=300`, first run 20 s after start.
- `auto_sync = False` removes the job. `reschedule()` re-applies the settings.

The heartbeat is the **resolution** of every trigger: a pulse of 5 minutes still only fires on a
30-minute heartbeat. (Neither value is editable in the UI today — see
[Known Issues](Known%20Issues.md).)

## Trigger boxes

A trigger is a `graph_node` of kind `trigger`, wired to `source` and/or `withdraw` boxes.

| `trigger_kind` | Fields | Due when |
| --- | --- | --- |
| `pulse` | `every_minutes` | `now ≥ last_checked + every_minutes`; `0` means every run |
| `schedule` | `cron` (5 fields, UTC) | A cron firing time fell in `(last_checked, now]` |

Never-polled is always due. Several triggers on one source: **any** being due is enough.

`When.due()` is the single implementation for both kinds. Sources measure from
`channel.last_checked_at`; Withdraw boxes from the box's own `last_fired_at`.

### What is wired

- `triggers_for` → `{channel_pk: [trigger boxes]}`, skipping disabled triggers and disabled source
  boxes.
- `polling_plan` → `{channel_pk: [When]}`. A channel absent from it is **never** polled by the
  heartbeat.
- `triggers_for_withdrawals` / `due_withdrawals` → Withdraw boxes due to pull.

### Pressing ▶ on a trigger

`POST /graph/nodes/{id}/fire` (and `/backfill` for reach back), both through `_set_off` in `web/routes/canvas/running.py`:

1. Collect the channels (`pulse_targets`), source **boxes** (`wired_sources`) and Withdraw boxes
   (`wired_withdrawals`) it reaches. Nothing wired → 400.
2. Stamp the trigger's `last_fired_at`.
3. Only Withdraw boxes → `withdraw_now` inline, no thread.
4. Otherwise `claim()` the run token (so the canvas immediately polls the right run) and start
   `run_sync(force=True, only=…, sources=…, withdrawals=…, fired_by=…)` in a daemon thread.

`force=True` skips the due check. `sources` keeps the run to the paths this trigger starts.

## Cron and weekdays

APScheduler numbers weekdays from Monday; cron from Sunday. `cron_trigger()` rewrites the
day-of-week field to names (`sun`…`sat`) before handing it over, so `0 9 * * 1` is Monday, as
everywhere else. `check_cron()` validates and normalises whitespace.

## Why triggers, not per-source intervals

A source that is fetched for reasons the canvas cannot show is a source filling feeds nobody can
explain. Making the trigger the only reason to poll means the canvas is the whole schedule.

**Related:** [The Sync Engine](The%20Sync%20Engine.md) · [Reading Windows](Reading%20Windows.md)
