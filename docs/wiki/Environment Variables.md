# Environment Variables

Read once at start-up. Change one and restart. Everything else is set in the app.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PAMPHLETS_ADMIN_USER` | — | Admin username. Setting this **and** the password turns sign-in on. |
| `PAMPHLETS_ADMIN_PASSWORD` | — | Admin password. Re-read on every start: changing it is how you get back in. |
| `PAMPHLETS_SESSION_DAYS` | `30` | How long a sign-in lasts. |
| `PAMPHLETS_PUBLIC_URL` | `http://localhost:8080` | The address people open. A plugin's sign-in redirect URI is this plus `/oauth/callback`. |
| `PAMPHLETS_PLUGIN_<PLUGIN>_<SETTING>` | — | Any plugin's setting for everyone, while its card under Admin → Plugins leaves it blank. Upper case, with anything but letters and digits as `_`. |
| `PAMPHLETS_PLUGIN_YOUTUBE_CLIENT_ID` | — | The YouTube plugin's Google OAuth client id. |
| `PAMPHLETS_PLUGIN_YOUTUBE_CLIENT_SECRET` | — | Its client secret. |
| `PAMPHLETS_PLUGIN_YOUTUBE_API_KEY` | — | Optional Google API key, for looking up `@handles` before anyone has signed in. |
| `PAMPHLETS_DATA_DIR` | `./data` (`/data` in Docker) | Where the database and your own plugins live. |
| `PAMPHLETS_DATABASE_URL` | SQLite in the data dir | Any SQLAlchemy URL. Only SQLite is tested — see note below. |
| `PAMPHLETS_HOST` | `0.0.0.0` | Listen address inside the container. |
| `PAMPHLETS_PORT` | `8080` | Listen port inside the container. |
| `PAMPHLETS_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `TZ` | `UTC` | Container time zone, for log timestamps. Schedules are always UTC. |

Compose-only (used by `docker-compose.yml`, not by the app):

| Variable | Default | Meaning |
| --- | --- | --- |
| `PAMPHLETS_BIND` | `0.0.0.0:8080` | Host side of the published port. `127.0.0.1:8080` keeps it local. |
| `PAMPHLETS_IMAGE` | `pamphlets:latest` | Image to run, e.g. from a registry. |
| `PAMPHLETS_DATA` | `pamphlets-data` | Named volume or absolute host path for `/data`. |
| `PAMPHLETS_MEMORY_LIMIT` | `512M` | Container memory limit. |

Put them in `.env` beside `docker-compose.yml`. It is gitignored.

**Database note:** other databases are not tested, and at least one column is too narrow for
PostgreSQL's strict length checks. Use SQLite.

**Related:** [Installing](Installing.md) · [Running in Production](Running%20in%20Production.md)

## Renamed

`PAMPHLETS_CLIENT_ID`, `PAMPHLETS_CLIENT_SECRET` and `PAMPHLETS_API_KEY` are no longer read: they are the
YouTube plugin's settings now. The first start after upgrading copies any values they held, and any
the Settings page held, into the plugin's settings for everyone, and says so in the log. Rename them
to `PAMPHLETS_PLUGIN_YOUTUBE_CLIENT_ID` and so on, or remove them and use the plugin's card.
