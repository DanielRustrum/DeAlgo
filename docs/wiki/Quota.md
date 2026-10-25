# Quota

Some services ration what can be asked of them: so many units a day, and a refusal after that.
A plugin that signs in to one says so — how many units a day, what each request costs, when the
service's day starts — and Pamphlets keeps count. **Reading every source is free**: sources are read
through their public feeds, and quota is only spent when a plugin talks to its service as you.

## What costs what

Each plugin says what its requests cost, in the service's own units; its card under
**Admin → Plugins** lists them. Writing — adding to or removing from a playlist on the service,
creating one — usually costs the most, and lookups by name more than lookups by id. Feeds that live
in Pamphlets cost nothing.

## When it runs out

Pamphlets keeps its own count and stops writing **before** the service refuses — even counting
requests the service rejected. Checking sources and filling Pamphlets's own feeds carry on. What was
owed to the service is written after the allowance resets, at the start of the service's day, in its
time zone.

See today's use in the plugin's block under **Settings → Plugins**. A run that stopped on quota
says so in [the run log](The%20Run%20Log.md).

## One allowance for everyone

An allowance usually belongs to the OAuth client, and every account here signs in through the same
one, the one the admin set on the plugin. So there is one count for the whole install: every
account spends from it, and each sees the same number.

The admin can change the daily figure and how much is held back from syncing on the plugin's card
under **Admin → Plugins** (**Daily quota**, **Held back from syncing**), for a client the service
has granted more.

**Related:** [Connecting an Account](Connecting%20an%20Account.md) · [Feeds](Nodes/Feeds.md)
