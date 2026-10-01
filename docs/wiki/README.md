# De-Algo User Wiki

De-Algo follows the sources you choose and fills feeds you own. Nothing is recommended, ranked or
injected: what you wire up is what you get, in the order you set.

This wiki explains every feature. Each page covers one thing. Every page and section is listed in
the [Table of Contents](Table%20of%20Contents.md).

## Getting set up

- [Installing](Installing.md) — run De-Algo with Docker or Python.
- [Environment Variables](Environment%20Variables.md) — every setting read at start-up.
- [Running in Production](Running%20in%20Production.md) — reverse proxies, clusters, Portainer.
- [Accounts](Accounts.md) — sign-in, the admin, and members.
- [Connecting YouTube](Connecting%20YouTube.md) — only needed to write to real YouTube playlists.

## Reading

- [The Feed Page](The%20Feed%20Page.md) — where you browse what arrived.
- [Focus Mode](Focus%20Mode.md) — watch and read one item after another.
- [Watched Items](Watched%20Items.md) — marking items done and clearing them out.
- [The Raw List](The%20Raw%20List.md) — every item De-Algo has seen, and why it went where it did.

## Building your setup

- [The Configuration Canvas](The%20Configuration%20Canvas.md) — boxes, wires and the palette.
- [Testing a Flow](Testing%20a%20Flow.md) — see what a run would do without doing it.
- [The Run Log](The%20Run%20Log.md) — what each run did, line by line.

## Nodes

Every box and piece on the canvas. See [Nodes](Nodes/README.md).

- [Triggers](Nodes/Triggers.md) — when sources are checked.
- [Sources](Nodes/Sources.md) — where items come from.
- [Newsletters](Nodes/Newsletters.md) — follow a newsletter by its address.
- [Filter](Nodes/Filter.md) — let some items through and hold others back.
- [Sort](Nodes/Sort.md) — choose the order items arrive in.
- [Tag](Nodes/Tag.md) — mark items for a Filter further on.
- [Decay](Nodes/Decay.md) — limit how long you spend on each item.
- [Expire](Nodes/Expire.md) — take items out of a feed after a while.
- [Feeds](Nodes/Feeds.md) — where items end up.
- [Repositories](Nodes/Repositories.md) — hold items now, release them later (Deposit and Withdraw).
- [Augmentations](Nodes/Augmentations.md) — pieces that slot under a box and change what it does.
- [Reading Windows](Nodes/Reading%20Windows.md) — limit when a feed can be read (Timer, Reset, Alive).
- [Groups](Nodes/Groups.md) — arrange the canvas and share setups.

## Managing

- [Settings](Settings.md) — what each account can change.
- [Quota](Quota.md) — YouTube's daily API allowance.
- [Backup and Restore](Backup%20and%20Restore.md) — save and reload your own setup.
- [Moving an Instance](Moving%20an%20Instance.md) — every account, encrypted, to another machine.
- [Plugins](Plugins.md) — add, fetch, permit and pause plugins (admin only).
- [Installing as an App](Installing%20as%20an%20App.md) — home-screen install and offline reading.
- [Command Line](Command%20Line.md) — drive De-Algo from a shell or cron.
- [Troubleshooting](Troubleshooting.md) — when something is not arriving.

## Extending

- [Creating A Plugin](Creating%20A%20Plugin/GETTING%20STARTED.md) — add new sources and conditions in Lua.
