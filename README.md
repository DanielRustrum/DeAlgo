# De-Algo

Watches different channels provided by the user and updates a playlist on YouTube specified by the
user. The intent is to provide a feed that isn't subject to the algorithm.

You pick the channels. Every new upload goes into one playlist, oldest first, and nothing else gets
in. No recommendations, no autoplay rabbit hole, no "you might also like".

---

## How it works

1. **Polling is free.** Each watched channel is checked through YouTube's public Atom feed
   (`/feeds/videos.xml?channel_id=…`), which costs no API quota and needs no credentials. That feed
   also reveals which uploads are Shorts, because they link as `/shorts/<id>`.
2. **Routing is yours.** Each channel feeds whichever playlists you assign it — one, several, or
   none. Science channels into one playlist, music into another, a favourite into both.
3. **Filtering is yours.** Each channel has its own Shorts switch, and can skip live streams and
   premieres, bound the length, require or reject a title pattern, and cap how many videos a single
   sync may add.
4. **Only writing costs quota.** The YouTube Data API is used solely for what the feed cannot do:
   resolving a `@handle` to a channel id, reading durations, and inserting playlist items.
5. **Everything is remembered.** Every video De-Algo has ever seen is recorded with what it decided
   and why, so a video is never added twice and a restart never loses its place.

## Quick start

```bash
cp .env.example .env      # optional: Google credentials can also be typed into the UI
make up                   # builds if needed, then waits until the container is healthy
```

`make` on its own lists every target: `up`, `down`, `restart`, `logs`, `ps`, `shell`, `build`,
`clean`, and the CLI passthroughs below. Plain `docker compose up -d` works just as well.

Open <http://localhost:8080> and press **Tour** in the header for a guided walk from an empty
install to a daily habit — it ticks off each step as you complete it, and can be hidden from
Settings once you are done with it.

Or set it up directly. Go to **Configuration**. **New feed** makes somewhere for videos to
go; **Track content** adds a channel by its URL, `@handle` or bare `UC…` id and links it to that
feed. Each box does both halves, so either order works. A Google account is only needed once a feed
is backed by a real YouTube playlist.

To run it without Docker:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m dealgo serve      # http://localhost:8080
```

## The Feed

The **Feed** tab is where you actually watch. Each feed is a collapsed section — open one and you get
a grid of cards with thumbnail, channel, age and length. **Clicking a thumbnail opens theater mode**
at that video, inside the feed you clicked from and in that feed's order, so one click starts a
sitting rather than a single play.

Sections are collapsed by default, so the page opens as an index of your feeds. A search box at the
top matches feed names and their tags.

- **Unwatched** is each feed's default view; the heading shows how many are held back (`2 of 3`).
  Switch that feed to **everything** to see watched ones dimmed.
- **Oldest first** is the default, matching the order the playlist itself reads in. **Newest first**
  is a click away. Both are per feed, and remembered.
- Mark something watched from its card, then use **Remove watched** to clear those out of the
  playlists for real.
- A section that is fully caught up says so rather than showing an empty box.

### Theater mode

**Theater ▶** plays the unwatched queue straight through: a full-width player that marks each video
watched as it ends and starts the next one. Start from the whole feed, from one playlist's section,
or from a particular card.

**Skip** moves on without marking watched; **Watched · next** does both by hand. A video that will
not play — private, deleted, embedding disabled — is skipped rather than stranding the queue on it.

Each advance asks the server for the next video instead of walking the list the page was given, so a
theater tab left open overnight cannot resurrect something watched or removed since. A video sitting
in two playlists is queued once.

This is the one page that loads a script from YouTube: auto-advance needs the IFrame Player API to
report when a video ends, which a plain embed cannot. If that script does not arrive, the page says
so and links out rather than showing a blank stage.

## Feeds

A **feed** is a list De-Algo keeps filled from the channels you assign to it. Create one with
**New feed** on the Configuration page, which asks three things in one box:

1. **What backs it** — a *generic feed* with no YouTube playlist behind it, a new playlist De-Algo
   creates on your account (you choose private, unlisted or public), or a playlist already there.
2. **Which channels fill it** — optional, and editable later either way round.

A **generic feed** is the one that needs nothing from Google: its videos are discovered, filtered and
watchable on the Feed and Theater pages, with the same channels, filters, limits and watched
tracking as any other. Only the writing to YouTube is skipped — so no account, no API quota, no
playlist.

**Google is optional throughout.** With no account connected — or one whose grant has lapsed — every
feed behaves like a generic one: channels are polled, videos are filtered and collected, and the Feed
and Theater pages work as usual. Nothing is added to or removed from YouTube, and the feeds that point
at a playlist are greyed out and marked *local only*, with a banner saying so. What they collect
meanwhile is not lost: it is still owed to the playlist, and goes in on the first sync after you
connect, paced by the daily quota like any other write.

Assignments go either way round: click a feed's channel count to pick which channels fill it, or open
a channel and tick the feeds it should fill. The channel list filters by feed, so you can see what
fills what at a glance — including a **no playlist** filter for channels queueing with nowhere to go.

A channel can fill several feeds at once. For YouTube-backed ones the video is inserted into each, at
50 quota units apiece; De-Algo records where every video landed, so the same video is never added to
the same playlist twice, and removing it from one does not disturb the others.

Linking a feed applies to future uploads. To backfill an older video, press **Queue** on it in the
**Raw** list — it will be added to any linked feed it is not already in.

**Rename** retitles a feed at any time. For a YouTube-backed one the playlist itself is renamed too,
so De-Algo's label and the playlist's own name cannot drift apart; it costs 50 quota units, and if
YouTube refuses the local name still changes and says so. A generic feed renames instantly with no
call at all.

**Unlink** cuts a feed loose from its YouTube playlist without losing the feed: it keeps its name,
channels, limits, fill order and the videos already in it, and carries on as a generic one. The
playlist over on YouTube is left exactly as it is.

**Remove** discards the feed itself — its channel links and the record of what went into it. Either
way the YouTube playlist and its videos stay where they are.

## Connecting YouTube

Writing to a playlist acts on your behalf, so it needs an OAuth grant rather than an API key.

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project and enable
   **YouTube Data API v3**.
2. Create an OAuth client of type **Web application**.
3. Add `http://localhost:8080/oauth/callback` as an authorized redirect URI. If you reach De-Algo at
   another address, set `DEALGO_PUBLIC_URL` to it and use that host instead — the redirect URI must
   match exactly.
4. Put the client id and secret in `.env` (or in Settings), then press **Connect YouTube account**.
5. Choose an existing playlist or have De-Algo create a new private one.

The refresh token is stored in the database, so this happens once.

### If Google blocks the sign-in

- **`Error 400: redirect_uri_mismatch`** — the URI in step 3 is not registered on the client, or not
  character-for-character identical. The Settings page prints the exact string with a copy button.
  Check you pasted it under *Authorized redirect URIs* and not *Authorized JavaScript origins*, and
  that the client is a **Web application** (a Desktop client has no redirect URI field at all).
- **`Error 403: access_denied` / "has not completed the Google verification process"** — the consent
  screen is in **Testing**, which only admits accounts on its *test users* list. Add your own Google
  account under **OAuth consent screen → Audience → Test users**.

  Google rejects the project's own owner account here as "not eligible for designation as a test
  user" — that account can already consent, so if the sign-in was still refused you were probably
  signed into a different Google account than the one owning the project.

Testing mode also **expires the refresh token after seven days**, which means reconnecting weekly.
Publishing the consent screen stops that. For a personal instance the app stays unverified, so
Google shows an "unverified app" interstitial once — *Advanced → Go to De-Algo (unsafe)* — and then
the grant lasts. De-Algo notices a dead grant on its next refresh and asks you to reconnect on the
dashboard rather than silently queueing videos forever.

### Quota

The default budget is 10,000 units a day. Polling spends none of it. Each video added to the
playlist costs 50 units — roughly 200 videos a day — and reading durations costs 1 unit per batch of
50. Resolving a channel by name falls back to a search, which costs 100, so pasting a `UC…` id or a
`/channel/` URL is the cheapest way to add one.

## Settings worth knowing

| Setting | Does |
| --- | --- |
| Poll interval | How often a sync runs. Free, so minutes are fine. |
| Check at most every (per channel) | The shortest gap between checks for one channel. A daily uploader does not need polling every 15 minutes. |
| Backfill on a new channel | How many recent uploads a newly added channel contributes when **Track content** is left on *Default*. The rest of its feed is marked *ignored* rather than dumped into a playlist. |
| Max size (per playlist) | Above 0, the oldest entries are removed once that playlist passes this — a rolling feed instead of an ever-growing one. |
| Max added per sync (per playlist) | Most videos that playlist will take in one run. Anything held back is queued for the next run, not dropped. Pairs with the fill order to spread a tight quota across playlists. |
| New channels (per playlist) | Whether a newly added channel starts feeding this playlist. The first playlist you add is a default; later ones are opt-in. |
| Shorts threshold | The length at or under which something counts as a Short. Per channel, Shorts are toggled on or off from the Channels list. |
| Max added per sync | Per channel. Keeps one prolific uploader from flooding the playlist in a single pass. |

Videos can be re-queued or ignored by hand from the **Raw** page — every video De-Algo has seen,
with what it decided and why.

## What gets taken from a channel

Every upload is exactly one of three kinds, and each has its own switch in the Channels list:

- **Videos** — ordinary uploads: anything that is neither a Short nor a broadcast. On by default.
- **Shorts** — off by default. The feed marks them (they link as `/shorts/<id>`), so this works with
  no API credentials at all; the length threshold in Settings catches any the feed does not flag.
- **Live** — live streams and scheduled premieres. Off by default.

Follow a channel only for its Shorts by switching Videos off and Shorts on. Switching all three off
means nothing from that channel is ever added, so the list marks it **takes nothing** rather than
leaving you to wonder.

Turning either **on** also queues what that channel already skipped for that reason, so the switch
applies to what it passed over rather than only to future uploads. A stream skipped while it was
live has usually finished by the next run, so you get the recording rather than the broadcast. The
two are independent: turning live on leaves skipped Shorts skipped.

Turning either **off** stops future ones and leaves anything already in a playlist alone.

## How much history to take

**Track content** asks how far back to reach on a channel's first check: nothing, the last week,
month or three months, everything the feed still lists, or the global default count under Settings.
Anything older is recorded as *ignored* rather than added, so it is never picked up later either.

YouTube's channel feed only lists the newest ~15 uploads, so a long window reaches as far as that and
no further. The choice applies to the first check only — an older video surfacing afterwards is
treated as new, as it should be.

## How often each channel is checked

The global poll interval decides how often a sync runs. Each channel then has its own **minimum**
gap between checks, set from the Channels list — hourly, daily, weekly, or a custom number of
minutes. A channel that posts once a week does not need looking at every fifteen minutes.

It is a floor, not a schedule: a channel is polled on the first sync at or after its gap elapses, so
the real spacing is rounded up to the poll interval. **Sync now** respects it, because a minimum
anything can override is not a minimum — use **Force** beside it (or `dealgo sync --force`) to poll
every channel regardless. Forcing ignores the gaps, not the pause switch: a paused channel stays
paused. A channel that has never been checked is always due, and the list shows when each one is
next up. Forced runs are marked in the run log.

Waiting to poll does not stall anything already queued: a throttled channel's pending videos are
still published on every run.

## Fill order

When the quota runs short, what gets in first is a choice, so both lists are ordered explicitly with
the ▲▼ controls:

- **Channels**, on the Configuration page — the order videos are inserted in. The channel you care most
  about gets into the playlist before the budget runs out.
- **Feeds**, in the Feeds panel on the Configuration page — which playlist a video reaches first when it
  feeds several.

Within a channel the order stays chronological, so playlists still read oldest-first. With every
channel at the same priority — which is how they start — the behaviour is exactly chronological,
as it was before ordering existed.

## Clearing out what you have watched

YouTube gives applications no access to your watch history — the `watchHistory` playlist has returned
nothing since 2016 — so De-Algo cannot detect this for you. You tell it, and it acts only when asked.

1. Press **Watched** on a video (or **Mark playlist watched** once you have caught up on a batch).
2. Press **Remove N watched from playlist**. De-Algo deletes exactly those items, from every playlist
   the video is in.

The video's record is deliberately kept. That record is what stops the next sync from seeing the
upload in the channel feed and putting it straight back — the one property the tests guard hardest.
Nothing is ever removed on a schedule or as a side effect of a sync; removal happens only when you
press the button or run the command.

If you delete an item from the playlist in YouTube instead, that also sticks: De-Algo already knows it
has handled that video and will not re-add it. Marking it watched afterwards simply reconciles the
record.

Removal costs 50 quota units per video, the same as adding one.

## Command line

The same container runs headless:

```bash
make sync                          # one pass, then exit
make sync FORCE=1                  # ignore every channel's minimum gap
make add CHANNEL=@GoogleDevelopers # watch a channel
make channels                      # list what is watched
make info                          # show configuration

docker compose run --rm dealgo watched dQw4w9WgXcQ   # mark videos watched
docker compose run --rm dealgo remove-watched        # clear them from the playlist
```

Each is a thin wrapper over `docker compose run --rm dealgo <command>`, so the container is the only
thing you need installed.

## Portainer

[stack.yml](stack.yml) is a self-contained stack: a prebuilt image, no build context, nothing that
needs a checkout on the host.

1. **Stacks → Add stack**, then either paste `stack.yml` into the web editor or point Portainer at
   this repository (`stack.yml` as the compose path).
2. Fill in the environment variables in Portainer's own env section — at minimum `DEALGO_IMAGE`,
   `DEALGO_PUBLIC_URL`, and the Google client id and secret.
3. Deploy.

For updates, enable **Automatic updates** on the stack: polling watches the image digest, or the
webhook gives you a URL to POST to. Setting that URL as a `PORTAINER_WEBHOOK` secret makes every
successful build redeploy the stack on its own. The container also carries the Watchtower label if
you would rather use that.

### Building the image

[.gitea/workflows/publish.yml](.gitea/workflows/publish.yml) runs the tests, then builds and pushes
`repo.home.app/rusty/dealgo` for amd64 and arm64 on every push to `main`, tagging `latest`, the
short commit sha, and any `v*` release tag. It is written in GitHub Actions syntax, which Gitea and
Forgejo both read, so it also works unchanged on GitHub with `REGISTRY: ghcr.io`.

Without a runner, push by hand:

```bash
make publish                      # host architecture
make publish-multiarch            # amd64 + arm64, needs buildx
make publish TAG=v0.1.0           # a release tag
```

Pin `DEALGO_IMAGE` to a sha or version tag if you would rather approve each update than track
`latest`.

## Running in a cluster

```bash
docker compose -f docker-compose.yml -f compose.cluster.yml up -d   # or: make up CLUSTER=1
```

The overlay drops the published port and puts the container on an existing
`proxy` network with Traefik labels — swap those for whatever your cluster runs. On Compose older
than v2.24 (no `!reset`), skip the overlay and set `DEALGO_BIND=127.0.0.1:8080` instead so only a
local proxy can reach it.

Four things actually matter:

- **Run exactly one instance.** De-Algo is a single SQLite file and an in-process scheduler. A second
  replica would double-insert into your playlists and fight over database locks. The compose file
  pins `replicas: 1` and sets `update_config.order: stop-first`, so a redeploy stops the old
  container before starting the new one rather than briefly running two.
- **Set `DEALGO_PUBLIC_URL` to the public URL** — `https://dealgo.example.com`, not the container
  address — and add `<that>/oauth/callback` to the Google client's authorized redirect URIs. De-Algo
  builds the OAuth redirect from this rather than from the incoming request, so a proxy cannot get it
  wrong. It trusts `X-Forwarded-*`, so TLS terminating at the proxy is fine.
- **Give it a subdomain, not a subpath.** Links and assets are served from the root; `/dealgo/…`
  works only if your proxy strips the prefix.
- **Keep the volume on local disk.** SQLite over NFS or CIFS corrupts, because their locking lies.
  Pin the service to the node holding the volume.

The container runs as uid 10001 with a read-only root filesystem, no capabilities and
`no-new-privileges`; `/data` is the only writable path. If you bind-mount a host directory instead of
a named volume, `chown 10001:10001` it first.

For `docker stack deploy`, build and push the image first and set `DEALGO_IMAGE` — Swarm ignores
`build:`, and warns about `restart:` in favour of the `deploy:` block that is already there.

## Backup

**Settings → Backup** downloads one JSON file holding the whole setup: settings, feeds, channels,
their filters, limits and fill order, and which feeds each channel fills. Rows reference each other
by YouTube's own channel and playlist ids rather than database row numbers, so the file means the
same thing on another machine.

**No credentials are in it** — not the YouTube sign-in, not the Google client id and secret. A backup
sits in a Downloads folder for years, and both are re-entered in a minute. Neither is the video
history: this is the shape of the setup, not a record of everything De-Algo has ever seen.

**Load backup** reads a file back in. Feeds and channels are matched by their YouTube ids, so
anything the file names is created or brought up to date, and nothing is deleted — restoring onto a
live install merges rather than replacing it. Files written by earlier versions still restore,
including the history and client id they used to carry.

On a new machine: restore the file, paste the client id and secret, then press **Connect YouTube
account**. Channels come back marked as never checked, so the backfill limit applies on the first
sync instead of a whole feed counting as new.

For scripted or scheduled backups:

```bash
make backup                                   # writes ./de-algo-backup.json
docker compose run --rm -T dealgo export -o /data/backup.json
```

Copying `dealgo.sqlite3` is still the fastest way to move an install wholesale, history and all.

## Data

Everything lives in one SQLite file at `/data/dealgo.sqlite3`, on the `dealgo-data` volume. Back it
up by copying that file; move installs by moving it. `DEALGO_DATABASE_URL` points at another
database if you would rather use Postgres. Schema changes are applied on start, so upgrading is
`docker compose pull && docker compose up -d`.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `DEALGO_PUBLIC_URL` | `http://localhost:8080` | Where the browser reaches De-Algo; the OAuth redirect URI is this plus `/oauth/callback`. |
| `DEALGO_CLIENT_ID` / `DEALGO_CLIENT_SECRET` | — | Google OAuth client. Can be set in the UI instead. |
| `DEALGO_API_KEY` | — | Optional. Lets De-Algo resolve handles and read durations before an account is connected. |
| `DEALGO_DATA_DIR` | `./data` (`/data` in Docker) | Where the database is created. |
| `DEALGO_DATABASE_URL` | SQLite in the data dir | Any SQLAlchemy URL. |
| `DEALGO_HOST` / `DEALGO_PORT` | `0.0.0.0` / `8080` | Listen address inside the container. |
| `DEALGO_BIND` | `0.0.0.0:8080` | Host side of the published port. `127.0.0.1:8080` keeps it local. |
| `DEALGO_IMAGE` | `dealgo:latest` | Image to run, for deploying from a registry. |
| `DEALGO_DATA` | `dealgo-data` | Named volume or absolute host path for the database. |
| `DEALGO_LOG_LEVEL` | `INFO` | Logging verbosity. |

## Development

```bash
.venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest
```

The tests cover feed parsing, channel-reference parsing, the filter rules, the web routes and their
htmx responses, the watched/removal flow, and the sync engine end to end against a fake YouTube — no
network, no credentials.

Layout:

```
dealgo/
  youtube/     feeds.py (free Atom polling) · api.py (Data API) · oauth.py
  services/    sync.py (the engine) · filters.py · channels.py · playlists.py
               watched.py · auth.py
  web/         app.py (FastAPI) · templates/ · static/
  models.py    the whole schema · db.py · scheduler.py
```

The frontend is server-rendered HTML driven by [htmx](https://htmx.org) — vendored into
`dealgo/web/static/`, so the container needs no CDN and no build step. Pages navigate through
`hx-boost`, the sync button polls its own status and announces a finished run with an `HX-Trigger`
header, and the panels listening for that event refresh themselves. Every htmx route also answers a
plain form post with a redirect, so the app still works with JavaScript switched off.

## License

MIT — see [LICENSE](LICENSE).
