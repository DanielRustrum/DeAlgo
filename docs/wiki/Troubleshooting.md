# Troubleshooting

Start with [The Run Log](The%20Run%20Log.md): it says what each run did with each source, and why.
Use [Testing a Flow](Testing%20a%20Flow.md) to see where items would go.

## Nothing arrives from a source

1. **Is it switched on?** New sources start paused, and wiring them does not switch them on. Open the
   box, tick **Active**, save.
2. **Is a trigger wired into it?** Without one it is never checked. The run log says *nothing polls
   this — wire a trigger to it*.
3. **Has its trigger come round?** Triggers are looked at every 30 minutes. Press **Run now** to check
   immediately.
4. **Does a path reach a feed?** Items with nowhere to go stay *pending*.
5. **Did a filter hold it?** [The Raw List](The%20Raw%20List.md) shows *skipped* items with the reason.
6. **Is it just slow?** Each source delivers at most 5 new items per run.

## A source leaves some of what it publishes out

A plugin can sort what a source publishes into kinds, each a switch under **Takes** in the source's
panel, and start some of them off. Turn on the ones you want.

## A source says it is waiting

The site asked Pamphlets to slow down. Pamphlets waits as asked and tries again; the source's page
says how long. Where the source's plugin offers one, set a **Mirror** in the source's panel.

## Items never reach a feed on a service

- **Not signed in** (Settings → Plugins), or the grant expired — see [Connecting an Account](Connecting%20an%20Account.md).
- **Quota spent** — writing resumes when the service's day starts again. See [Quota](Quota.md).
- **Not that service's item** — only the plugin's own items can go into a playlist on its service; others are skipped.

## A condition does nothing

- Its **plugin is switched off** — the piece says so. See [Plugins](Plugins.md).
- **Length** conditions need an item's length, which some sources only give a plugin that is signed in.
- Two conditions of the same kind under one Filter: only the nearest applies. See [Filter](Nodes/Filter.md).
- It is **loose** — slotted into nothing. Drag it onto a box.

## A feed is shut

It has [reading windows](Nodes/Reading%20Windows.md). List view says when it opens. Times are UTC.

## Signing in to a service fails

See [Connecting an Account](Connecting%20an%20Account.md#if-the-service-refuses-the-sign-in).

## Locked out

Change `PAMPHLETS_ADMIN_PASSWORD` and restart. See [Accounts](Accounts.md).

**Related:** [The Run Log](The%20Run%20Log.md) · [Sources](Nodes/Sources.md) · [Triggers](Nodes/Triggers.md)
