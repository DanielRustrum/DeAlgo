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

## A YouTube channel takes no Shorts or live streams

New channels take Videos and Posts only. Turn on **Shorts** or **Live** under **Takes** in the
source's panel.

## A source says it is waiting

The site asked De-Algo to slow down (Reddit does this). De-Algo waits as asked and tries again; the
source's page says how long. For Reddit, set a **Mirror** in the source's panel.

## Items never reach YouTube

- **No Google account**, or its grant expired — see [Connecting YouTube](Connecting%20YouTube.md).
- **Quota spent** — writing resumes after midnight Pacific. See [Quota](Quota.md).
- **Not a YouTube video** — only YouTube videos can go into a YouTube playlist; others are skipped.

## A condition does nothing

- Its **plugin is switched off** — the piece says so. See [Plugins](Plugins.md).
- **Length** conditions need video details, which need a connected account or API key.
- Two conditions of the same kind under one Filter: only the nearest applies. See [Filter](Filter.md).
- It is **loose** — slotted into nothing. Drag it onto a box.

## A feed is shut

It has [reading windows](Reading%20Windows.md). The Feed page says when it opens. Times are UTC.

## Google sign-in fails

See [Connecting YouTube](Connecting%20YouTube.md#if-google-refuses-the-sign-in).

## Locked out

Change `DEALGO_ADMIN_PASSWORD` and restart. See [Accounts](Accounts.md).

**Related:** [The Run Log](The%20Run%20Log.md) · [Sources](Sources.md) · [Triggers](Triggers.md)
