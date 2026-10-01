# Repositories

A repository holds items now and releases them later. Use it to gather many sources in one place and
pull from it on your own schedule.

```
[Source A] ─┐
[Source B] ─┼─▶ [Deposit: News]          [Pulse] ──▶ [Withdraw: News] ──▶ [Feed]
[Source C] ─┘
```

## Deposit

Ends a path, like a feed. Items that reach it wait in the named repository. Its box shows how many
are waiting.

## Withdraw

Starts a path, like a source. When its trigger fires, it takes items out of the named repository and
sends them on through whatever it is wired to.

- **Repository** — the name to pull from.
- **How many to take** — per pull. Blank takes everything waiting.

A Withdraw with no [trigger](Triggers.md) never pulls on its own. **Run now** on its trigger pulls
straight away.

## Names

A Deposit and a Withdraw are joined only by sharing a name. Names ignore case and extra spaces, so
`News` and `news` are one repository. Several Deposits can fill one repository.

## Details

- Items are filtered on the way in and can be filtered again after the Withdraw.
- A pull happens at the end of a run, so it includes what that run just deposited.
- Depositing needs no quota, so it still happens when YouTube's quota is spent.

**Related:** [Triggers](Triggers.md) · [Sources](Sources.md) · [Feeds](Feeds.md)
