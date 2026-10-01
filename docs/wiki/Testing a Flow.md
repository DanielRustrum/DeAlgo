# Testing a Flow

See what a run would do, without doing it. Nothing is written, nothing is sent to YouTube, and no
quota is spent.

Press **Test** on a [trigger](Triggers.md). It takes up to 30 recent items from the sources that
trigger is wired to, and pushes them through the canvas as a real run would.

## What you see

- **Counts on every box** the items reached.
- **Each box's items**, split into what got through and what was held back, with the reason.
- **What each item would carry at that box** — its tags, Decay time and Expire lifetime, built up box
  by box in the order they are passed.
- **Withdraw boxes** wired to the trigger, and what they would release.

Only the paths out of the boxes this trigger is wired to are tested.

## Also useful

- A [Filter](Filter.md)'s **What it catches** button shows what that one box lets through and holds back.
- [The Raw List](The%20Raw%20List.md) shows what real runs decided.

**Related:** [The Run Log](The%20Run%20Log.md) · [Triggers](Triggers.md)
