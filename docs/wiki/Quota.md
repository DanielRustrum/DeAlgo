# Quota

Google gives each project 10,000 YouTube API units a day. De-Algo spends them only to talk to
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

So roughly 200 items a day can be added to YouTube playlists. Feeds that live in De-Algo cost nothing.
Add channels by `UC…` id or `/channel/` URL to avoid lookups.

## When it runs out

De-Algo keeps its own count and stops writing **before** Google refuses — even counting requests
Google rejected. Checking sources and filling De-Algo's own feeds carry on. What was owed to YouTube
is written after the allowance resets at **midnight Pacific time**.

See today's use under **Settings → How De-Algo spends quota**. A run that stopped on quota says so in
[the run log](The%20Run%20Log.md).

## Quota is per account

Each account connects its own Google account and keeps its own count.

Google's allowance is per **Cloud project**, though. If several accounts use the same OAuth client,
they share one 10,000-unit allowance while De-Algo counts each separately — so Google may refuse
before De-Algo expects. Give each heavy user their own client in Settings to avoid this.

**Related:** [Connecting YouTube](Connecting%20YouTube.md) · [Feeds](Nodes/Feeds.md)
