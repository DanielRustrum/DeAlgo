# Installing

De-Algo is one Python process with one SQLite file. Run it with Docker (recommended) or directly.

## With Docker

```bash
git clone <this repository> && cd dealgo
cp .env.example .env    # optional
make up                 # builds, starts, waits until healthy
```

Open <http://localhost:8080>. `make up` reports when the container is healthy.

Without `make`, use `docker compose up -d`.

Useful targets — run `make` alone for the full list:

| Target | Does |
| --- | --- |
| `make up` / `make down` | Start or stop. `down` keeps your data. |
| `make logs` | Follow the logs. |
| `make restart` | Restart the container. |
| `make shell` | Open a shell inside it. |
| `make clean` | Stop **and delete all data**. Asks you to type `yes`. |

## Without Docker

Needs Python 3.11 or newer.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m dealgo serve
```

`make dev` does the same and also loads `.env` and rebuilds the stylesheet and scripts first.

## First steps

1. Set an admin, or anyone who can reach the address can use De-Algo. See [Accounts](Accounts.md).
2. Open **Configuration** and build your first flow: a [source](Sources.md) wired to a
   [feed](Feeds.md), and a [trigger](Triggers.md) wired into the source to say when to check it. See
   [The Configuration Canvas](The%20Configuration%20Canvas.md).
3. [Switch the source on](Sources.md#adding-one) — new sources start paused.

A Google account is optional. You only need one to write into real YouTube playlists — see
[Connecting YouTube](Connecting%20YouTube.md).

## Where data lives

Everything is in one SQLite file: `/data/dealgo.sqlite3` in Docker (the `dealgo_dealgo-data` volume),
`./data/dealgo.sqlite3` otherwise. Copy that file to back up everything, history included. Schema
changes apply automatically on start, so upgrading is just pulling and restarting.

Keep the data on a local disk. SQLite over NFS or CIFS corrupts.

## Upgrading

```bash
git pull && make build && make up
```

Or, with a registry image: `docker compose pull && docker compose up -d`.

**Related:** [Environment Variables](Environment%20Variables.md) ·
[Running in Production](Running%20in%20Production.md)
