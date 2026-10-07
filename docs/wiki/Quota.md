# Quota

Google gives each project 10,000 YouTube API units a day. Pamphlets spends them only to talk to
YouTube on your behalf — **reading every source is free**.

## What costs what

| Action | Units |
| --- | --- |
| Checking any source, including YouTube channels | 0 |
| Reading details for up to 50 videos (length, views, likes) | 1 |
| Adding an item to a YouTube playlist | 50 |
| Removing an item (watched, expired, or over a feed's size) | 50 |
| Creating or renaming a playlist | 50 |
| Looking up a channel by name (when an `@handle` lookup falls back to search) | 100 |

So roughly 200 items a day can be added to YouTube playlists. Feeds that live in Pamphlets cost nothing.
Add channels by `UC…` id or `/channel/` URL to avoid lookups.

## When it runs out

Pamphlets keeps its own count and stops writing **before** Google refuses — even counting requests
Google rejected. Checking sources and filling Pamphlets's own feeds carry on. What was owed to YouTube
is written after the allowance resets at **midnight Pacific time**.

See today's use in the YouTube block under **Settings → Plugins**. A run that stopped on quota says
so in [the run log](The%20Run%20Log.md).

## One allowance for everyone

Google's allowance belongs to the **Cloud project**, and every account here signs in through the
same OAuth client, the one the admin set on the YouTube plugin. So there is one count for the whole
install: every account spends from it, and each sees the same number.

The admin can change the daily figure and how much is held back from syncing on the plugin's card
under **Admin → Plugins** (**Daily quota**, **Held back from syncing**), for a project that Google
has granted more.

**Related:** [Connecting YouTube](Connecting%20YouTube.md) · [Feeds](Nodes/Feeds.md)
