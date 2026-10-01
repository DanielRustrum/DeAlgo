# De-Algo

**Your feeds, wired by you. No algorithm in the loop.**

De-Algo follows the YouTube channels, subreddits, Bluesky accounts, newsletters and RSS feeds you
choose, and fills feeds you own with exactly what they publish — filtered, ordered and paced the way
you decide. Nothing is recommended, nothing is injected, nothing autoplays into the next rabbit hole.

It is self-hosted: one container, one database, your server.

---

## Why De-Algo

- **You choose what arrives.** Only the sources you follow. No "you might also like".
- **You see how it works.** Your setup is a visual flow on the Configuration canvas: sources on the
  left, feeds on the right, every rule in between visible as a box. If something arrives, you can
  point at the wire it came down.
- **You set the pace.** Limit a feed to ninety minutes a day, open it only in the evening, give each
  post a few minutes before moving on, let items expire, or hold them back and release a few at a
  time.
- **It writes back to YouTube.** Push videos straight into real YouTube playlists and watch them on
  your TV — Shorts and live streams filtered out if you want.
- **Polling is free.** Sources are read through their public feeds. YouTube's API quota is only spent
  on writing to playlists, and De-Algo keeps a ledger so it never runs out mid-run.
- **Extend it safely.** New sources and new filter conditions are small Lua plugins, run in a sandbox
  and granted only the permissions an admin approves.
- **Share it with your household.** Separate private accounts on one instance; the admin manages
  accounts, not anyone's feeds.
- **Read offline.** Install it as an app on your phone; pages you have opened stay readable.

## How it works

```
 Trigger ──▶ Source ──▶ Filter ──▶ Sort ──▶ Feed ──▶ you, or a YouTube playlist
 (when)      (where)    (what)    (order)   (read it here, with Timer / Reset / Alive)
```

1. A **trigger** decides when to check a source.
2. New items flow along the **wires** you drew, through **Filter**, **Sort**, **Tag**, **Decay**
   and **Expire** boxes.
3. They land in **feeds** — inside De-Algo, or in a real YouTube playlist.
4. You read them on the **Feed** page or one at a time in **Focus mode**.

## Quick start

```bash
git clone <this repository> dealgo && cd dealgo
cp .env.example .env          # optional: sign-in and Google credentials
make up                       # build, start, wait until healthy
```

Open <http://localhost:8080>, go to **Configuration**, and drop a **Source**, a **Feed** and a
**Trigger** onto the canvas. Wire Trigger → Source → Feed, switch the Source on (new sources start
off), and press ▶ on the trigger.

Full walkthrough: [Installing](docs/wiki/Installing.md).

## Documentation

| For | Start here |
| --- | --- |
| **Using De-Algo** — every feature, one page each | [User Wiki](docs/wiki/README.md) |
| **Writing plugins** — sources, conditions, the Lua API | [Creating A Plugin](docs/wiki/Creating%20A%20Plugin/GETTING%20STARTED.md) |
| **Working on De-Algo** — architecture, systems, algorithms, decisions | [Internal Documentation](docs/internal/README.md) |
| **API reference** — generated from the code (`make docs`) | [autodoc](docs/internal/autodoc/README.md) |
| **What's broken or missing** | [Known Issues](docs/internal/Known%20Issues.md) |

## Built with

Python 3.12 · FastAPI · SQLAlchemy · SQLite · APScheduler · htmx · TypeScript · Lua 5.5 (lupa) ·
Docker

## License

MIT — see [LICENSE](LICENSE).
