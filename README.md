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
a grid of cards with thumbnail, channel, age and length. **Clicking a thumbnail opens Focus mode**
at that item, inside the feed you clicked from and in that feed's order, so one click starts a
sitting rather than a single play.

Community posts sit in the same grid. A post wears its **first image** as its tile — the same one
Focus mode leads with — and a post with no image at all shows its opening words instead.

Sections are collapsed by default, so the page opens as an index of your feeds. A search box at the
top matches feed names and their tags.

- **Unwatched** is each feed's default view; the heading shows how many are held back (`2 of 3`).
  Switch that feed to **everything** to see watched ones dimmed.
- **Oldest first** is the default, matching the order the playlist itself reads in. **Newest first**
  is a click away. Both are per feed, and remembered.
- Mark something watched from its card, then use **Remove watched** to clear those out of the
  playlists for real.
- A section that is fully caught up says so rather than showing an empty box.

### Focus mode

**Focus ▶** goes through the unwatched queue straight through, marking each item done and starting
the next. Start from the whole feed, from one playlist's section, or from a particular card. (This
was called Theater mode; the old `/watch` address still redirects here.)

**Skip** moves on without marking watched; **Done · next** does both by hand. A video that will not
play — private, deleted, embedding disabled — is skipped rather than stranding the queue on it.

Videos and community posts share one queue, and each ends its own way:

- A **video** plays full width and advances when it ends.
- A **post** is laid out as tiles — its images in a grid, its text below — and advances on a timer,
  because a post has no end of its own. **Click the timer to hold it** while you are still reading,
  and click again to carry on. The default is 30 seconds; change it under Settings → *Reading time
  for a post*. Clicking a tile opens the full image.

Opening on a post does not start audio underneath it: the player is loaded ready for whatever comes
next, but muted of its own accord until a video's turn. A queue of nothing but posts loads no player
at all.

Each advance asks the server for the next item instead of walking the list the page was given, so a
tab left open overnight cannot resurrect something watched or removed since. Anything sitting in two
playlists is queued once.

This is the one page that loads a script from YouTube: auto-advance needs the IFrame Player API to
report when a video ends, which a plain embed cannot. If that script does not arrive, the page says
so and points at **Reload** rather than showing a blank stage.

## Feeds

A **feed** is a list De-Algo keeps filled from the channels you assign to it. Create one with
**New feed** on the Configuration page, which asks three things in one box:

1. **What backs it** — a *generic feed* with no YouTube playlist behind it, a new playlist De-Algo
   creates on your account (you choose private, unlisted or public), or a playlist already there.
2. **Which channels fill it** — optional, and editable later either way round.

A **generic feed** is the one that needs nothing from Google: its videos are discovered, filtered and
watchable on the Feed and Focus pages, with the same channels, filters, limits and watched
tracking as any other. Only the writing to YouTube is skipped — so no account, no API quota, no
playlist.

**Google is optional throughout.** With no account connected — or one whose grant has lapsed — every
feed behaves like a generic one: channels are polled, videos are filtered and collected, and the Feed
and Focus pages work as usual. Nothing is added to or removed from YouTube, and the feeds that point
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

Each kind of thing a channel publishes has its own switch on the channel's page:

- **Videos** — ordinary uploads: anything that is neither a Short nor a broadcast. On by default.
- **Shorts** — off by default. The feed marks them (they link as `/shorts/<id>`), so this works with
  no API credentials at all; the length threshold in Settings catches any the feed does not flag.
- **Live** — live streams and scheduled premieres. Off by default.
- **Posts** — community posts. On by default, and read in Focus mode rather than watched.

Follow a channel only for its Shorts by switching Videos off and Shorts on, or only for its writing
by leaving Posts on and the rest off. Switching every kind off means nothing from that channel is
ever added, so the list marks it **takes nothing** rather than leaving you to wonder.

Posts share the channel's per-run cap with its videos, so a channel that posts heavily can push a
video to the next run rather than dropping it. Raise that cap on the channel's page if you would
rather have both in one go.

Turning either **on** also queues what that channel already skipped for that reason, so the switch
applies to what it passed over rather than only to future uploads. A stream skipped while it was
live has usually finished by the next run, so you get the recording rather than the broadcast. The
two are independent: turning live on leaves skipped Shorts skipped.

Turning any of them **off** stops future ones and leaves anything already in a playlist alone.

### Community posts

Posts are the one thing De-Algo cannot ask an API for: **there is no Data API for community posts**,
in v3 or behind any scope. The only way to read them is the page a browser gets, so De-Algo parses
the `ytInitialData` blob out of a channel's Posts tab. That means:

- **It costs no quota and needs no account** — but it is unofficial, and YouTube can change the page
  shape without notice. Everything about it fails soft: a page that will not parse yields no posts,
  never an error, and the channel's videos are collected exactly as before.
- **It costs bandwidth.** A Posts page is around a megabyte, fetched once per channel per check, so
  a channel's minimum pull interval applies to its posts as well. Denying posts for a channel skips
  the fetch entirely.
- **Dates are approximate.** A post carries "5 days ago" and nothing else, so the timestamp is
  derived from that. It is precise enough to order a feed and no more.
- **Posts never reach YouTube.** No playlist can hold one, so a post lives in De-Algo only, whatever
  its feed is backed by. Marking one done removes it here and asks nothing of YouTube.

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

## On a phone

The layout answers to narrow screens rather than shrinking the desktop one.
Below tablet width the tabs move out of the top bar and into a drawer behind a
hamburger — five tabs, a brand and two sync buttons never shared a row honestly,
and a scrolling strip of them hides where you can go. The drawer slides in from
the right, over a scrim that closes it when tapped.

It is a checkbox and two labels, so **it works with JavaScript switched off**,
like everything else here; `menu.js` adds what CSS cannot — `aria-expanded` on
the button, Escape to close, and holding the page still behind the drawer.

Panels lose their margins, definition lists drop their label column, and in
Focus mode the player and the bar go edge to edge, because the only dimension a
phone has to spare is the one a 16:9 stage wants.

Touch is treated as its own thing, not as a width: `@media (pointer: coarse)`
grows the hit areas, keeps the card actions visible instead of waiting for a
hover that never comes, and sizes form fields at 16px, which is what stops iOS
zooming in when a field takes focus and never zooming back out. A tablet with a
keyboard keeps the tighter layout; a phone in landscape does not.

Installed to a home screen it runs full-screen, so the frame allows for a notch
with `env(safe-area-inset-*)`.

## Installing it as an app

De-Algo ships a web app manifest and a service worker, so a browser will offer
to install it — *Add to Home Screen* on iOS, *Install app* on Android and
desktop Chrome. It then opens in its own window with no browser chrome, themed
to match.

**It needs HTTPS.** Service workers only run in a secure context, which means
`https://` or `localhost`. Reached over plain HTTP at a LAN address, De-Algo
works exactly as before but installs nothing and caches nothing — no error, just
no offline. Putting it behind a reverse proxy with a certificate is what turns
the feature on. See [Running in a cluster](#running-in-a-cluster) for where the
public URL is set.

### What "offline" means here

Worth being plain about, because it is half of what people expect.

**Reading works offline, and says what it could not get.** The shell, the pages
you have already visited, and the thumbnails in them are cached, so the app
opens and the feed is there. Nothing is all-or-nothing:

- A page you have already loaded comes back, with a line saying it is a stored
  copy and may have moved on since.
- A page you have never loaded is named — *`/channels/9` has not been loaded
  before* — rather than a blank apology.
- A thumbnail that was never cached becomes a drawn *not loaded* tile in the
  app's own colours, so the card keeps its shape instead of showing a broken
  image.
- A panel that cannot refresh — the sync status, the activity list — keeps what
  it is already showing and gets a small **not refreshed — offline** tag. The
  content on screen is still true, it is just not current, and replacing it with
  an error would be strictly worse.

Cached images are capped at a few hundred so the store cannot grow without
limit, and everything is versioned by build, so a deploy retires the old copies.

**Writing does not.** Marking something watched, syncing, editing a feed — all
of those need the server, and offline they fail and say so. A banner appears
when the connection drops, and the buttons that cannot work are disabled rather
than left to fail on being pressed.

That split is not laziness, it is the architecture: De-Algo renders its pages on
the server from a database that lives there. The screen you see after marking
something watched is HTML the server built. A write queued in the browser could
not produce that screen, so it would either lie about having worked or leave the
page wrong — and the videos themselves stream from YouTube, which offline is not
going to do either. Reading what you already have is the honest offering.

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
.venv/bin/pip install -r requirements.txt pytest libsass mypy
.venv/bin/python -m pytest
make typecheck            # mypy --strict, then tsc --noEmit
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
  web/         app.py (FastAPI) · templates/ · scss/ · ts/ · static/ (both compiled)
  models.py    the whole schema · db.py · scheduler.py
```

The frontend is server-rendered HTML driven by [htmx](https://htmx.org) — vendored into
`dealgo/web/static/`, so the container needs no CDN. Pages navigate through `hx-boost`, the sync
button polls its own status and announces a finished run with an `HX-Trigger` header, and the panels
listening for that event refresh themselves. Every htmx route also answers a plain form post with a
redirect, so the app still works with JavaScript switched off.

### Types

Both languages are checked strictly, and `make typecheck` runs both.

**Python** is `mypy --strict` over the whole `dealgo` package — no untyped
definitions, no bare `dict` or `list`, no implicit `Any` leaking out of a
function. The package ships a `py.typed` marker, so anything importing it gets
those types too. The settings live in `pyproject.toml`.

Two dependencies ship no type information of their own: `libsass` and
`apscheduler`. They are named individually in the config rather than waved
through with a global ignore, so the gap is a listed exception instead of a
hole. Where a value crosses that boundary its type is stated at the call —
`css: str = sass.compile(...)` — rather than letting `Any` spread.

What YouTube returns is `JsonDict` (`dict[str, Any]`), defined in
`youtube/payload.py`. That is deliberate: it is someone else's JSON, and
strict typing at a boundary means being honest that the contents are unchecked
rather than inventing a shape for them.

The test suite is not part of the strict run. Annotating four hundred fixtures
and test functions buys little, and a fixture that builds half an object on
purpose should not have to describe it in full.

**TypeScript** covers the browser scripts, with `strict` plus the checks it
leaves out — `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`,
`noImplicitReturns` and the rest, in `tsconfig.json`.

That file is kept as plain JSON with no comments in it. `tsc` reads JSON with
comments quite happily and nothing else does, so a `//` in there compiles fine
and then fails in every editor, linter or script that opens the file as JSON —
which is why the settings are explained here instead.

`"module"` deserves a note. These scripts are plain `<script>` tags the page
includes, not modules — no bundler, no import map, nothing to resolve at
runtime. The setting that used to say so, `"module": "none"`, was deprecated in
TypeScript 6 and **removed in 7**, so it now reads `"esnext"` with
`"moduleResolution": "bundler"`. That changes nothing about the output: a file
with no `import` or `export` is a script whatever `module` says, and the emitted
JavaScript is byte-for-byte the same. It does mean that adding an `import` to one
of these files would quietly turn it into an ES module that a plain `<script
src>` cannot load — so if you ever need one, the page's script tag needs
`type="module"` to match. There are no `!`
assertions anywhere, and a test enforces that: an element the template always
renders is fetched through a helper that throws by name if it is missing, so
the types are proved rather than asserted. htmx and YouTube's IFrame API arrive
as plain script tags with no packages behind them, so `ts/globals.d.ts`
declares just the members De-Algo actually calls — anything else has to be
added there first.

### Scripts

The browser scripts are written as TypeScript in `dealgo/web/ts/` and compiled
to `dealgo/web/static/`. There are two programs, not one: the service worker has
no DOM and the page scripts have no worker globals, so `sw.ts` is built by
`tsconfig.sw.json` and everything else by `tsconfig.json`. `make js` runs both.

```bash
make js           # compile once
make watch-js     # recompile on save
make assets       # both the scripts and the stylesheet
```

Each file is the same shape: type declarations, named functions, and a single
call to its entry point at the bottom. No wrapper, no anonymous block. What a
Focus sitting has to remember — the item open, what has been skipped, the
player, the timer — lives in one `FocusSitting` object that is passed to each
function rather than captured in a closure, so any of them can be read on its
own.

That structure is load-bearing, not taste. These are plain scripts, and htmx
re-runs one every time it swaps that page in — visit Focus, leave, come back,
and `focus.js` executes a second time in the same document. A top-level
`const`, `let` or `class` throws *"already declared"* on that second run and
takes the page with it; a `function` declaration does not. That is why nothing
but functions sits at the top level, and a test enforces it.

**Edit the `.ts`, never the `.js` in `static/`** — the JavaScript is generated
and `make js` overwrites it. As with the stylesheet, the compiled output is
committed and ships in the package, so **running or containerising De-Algo
needs no Node** — only editing the scripts does. A test compiles afresh and
compares, so a source changed without a rebuild fails the suite rather than
reaching the container unnoticed. It skips where TypeScript is not installed,
which is every environment that only runs the app.

`htmx.min.js` is vendored, not compiled: it is somebody else's build.

### Styling

The stylesheet is written as SCSS partials in `dealgo/web/scss/`, one per area of the app, pulled
together by `app.scss`. Rebuild after editing any of them:

```bash
make css          # compile once
make watch-css    # recompile on save (needs inotify-tools)
```

`make dev` compiles first, so running locally never serves a stale stylesheet.

**Edit the partials, never `static/app.css`** — it is generated and minified, and `make css`
overwrites it. The compiled file is committed and ships inside the package, which is why running or
containerising De-Algo needs no compiler; only restyling does. A test compiles the sources and
compares, so a partial changed without a rebuild fails the suite rather than reaching the container
unnoticed. Tests that check a rule reached the stylesheet match on whitespace-stripped CSS, since the
minifier decides the layout.

Compilation is [libsass](https://sass.github.io/libsass-python/) — a Python wheel, so the toolchain
stays `pip`-only with no Node. It predates Sass modules, so the partials use `@import` rather than
`@use`, and `min()` and `hsl()` collide with Sass's own functions where a `var()` or a `calc()` is
involved (`_dialogs.scss` and `_tokens.scss` show the way around each).

Shared pieces live in `_tokens.scss`: the light and dark custom properties, a `surface` mixin for the
panel look, and a `still` mixin wrapping `prefers-reduced-motion`. Theming stays in CSS custom
properties rather than SCSS variables, because the light theme switches at runtime.

## License

MIT — see [LICENSE](LICENSE).
