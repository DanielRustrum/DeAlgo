# Settings

Each account has its own Settings.

## Google account

**Connect YouTube account**, **Reconnect** after a grant expires, or **Disconnect**. Disconnecting
keeps your history and stops writing to playlists. See [Connecting YouTube](Connecting%20YouTube.md).

The exact redirect URI to register with Google is shown here, with a copy button.

## Preferences

**This interface**

- **Hide the Tour button.** The tour stays at `/tour`.
- **Hide the "no sign-in required" notice** shown when no admin is set.
- **Hide the "connect a Google account" notices.**

These hide notices only, never the problems they describe.

**Google API credentials** — client id, client secret and an optional API key. Values set by
environment variables are used when these are blank. See
[Environment Variables](Environment%20Variables.md).

## Feeds on YouTube

Make a feed backed by a new or existing YouTube playlist. Needs a connected account. See [Feeds](Feeds.md).

## Back up your setup

Download or load a setup file. See [Backup and Restore](Backup%20and%20Restore.md) — and read what it
does not include.

## How De-Algo spends quota

Today's quota use and when it resets. See [Quota](Quota.md).

## Fixed values

These used to be settings and now keep their defaults:

| Value | Default |
| --- | --- |
| How often De-Algo wakes to check [triggers](Triggers.md) | 30 minutes |
| Items taken from a new source when no backfill is given | 3 |
| Longest video counted as a Short when the feed does not say | 60 seconds |
| Daily YouTube quota | 10,000 units |
| Quota held back for manual removals | 0 |

**Related:** [Accounts](Accounts.md) · [Quota](Quota.md)
