# Settings

Each account has its own Settings.

## Preferences

**This interface**

- **Hide the Tour button.** The tour stays at `/tour`.
- **Hide the "no sign-in required" notice** shown when no admin is set.
- **Hide the "connect a … account" notices**, when a plugin you publish through needs a sign-in.

These hide notices only, never the problems they describe.

## Plugins

A block for each plugin that has something for you: a service to sign in to, or settings each
account sets for itself. Each is marked with the plugin's badge and colour, the same as on its card
under Admin → Plugins. Your values and sign-ins are yours; changing them changes nothing for anyone
else. Plugins the admin has switched off are not listed.

**Signing in.** A plugin that writes back to its service as you — YouTube, filling playlists — has
**Connect … account**, **Reconnect** after a grant expires, and **Disconnect**. Disconnecting keeps
your history and stops writing to that service. Where the service has a daily allowance, the block
shows how much of it is spent today, for everyone on this De-Algo. See
[Connecting YouTube](Connecting%20YouTube.md) and [Quota](Quota.md).

**Feeds on YouTube.** The plugin feeds are published through (YouTube) also has a section for
making a feed backed by a new or existing playlist on that service. Needs a connected account. See
[Feeds](Nodes/Feeds.md).

Settings that apply to everyone, such as a plugin's OAuth client, are the admin's, on the plugin's
card under Admin → Plugins.

## Back up your setup

Download or load a setup file. See [Backup and Restore](Backup%20and%20Restore.md) — and read what it
does not include.

## Fixed values

These used to be settings and now keep their defaults:

| Value | Default |
| --- | --- |
| How often De-Algo wakes to check [triggers](Nodes/Triggers.md) | 30 minutes |
| Items taken from a new source when no backfill is given | 3 |

**Related:** [Accounts](Accounts.md) · [Quota](Quota.md)
