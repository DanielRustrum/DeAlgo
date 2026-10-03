# Environment Variables

Read once at start-up. Change one and restart. Everything else is set in the app.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DEALGO_ADMIN_USER` | — | Admin username. Setting this **and** the password turns sign-in on. |
| `DEALGO_ADMIN_PASSWORD` | — | Admin password. Re-read on every start: changing it is how you get back in. |
| `DEALGO_SESSION_DAYS` | `30` | How long a sign-in lasts. |
| `DEALGO_PUBLIC_URL` | `http://localhost:8080` | The address people open. A plugin's sign-in redirect URI is this plus `/oauth/callback`. |
| `DEALGO_PLUGIN_<PLUGIN>_<SETTING>` | — | Any plugin's setting for everyone, while its card under Admin → Plugins leaves it blank. Upper case, with anything but letters and digits as `_`. |
| `DEALGO_PLUGIN_YOUTUBE_CLIENT_ID` | — | The YouTube plugin's Google OAuth client id. |
| `DEALGO_PLUGIN_YOUTUBE_CLIENT_SECRET` | — | Its client secret. |
| `DEALGO_PLUGIN_YOUTUBE_API_KEY` | — | Optional Google API key, for looking up `@handles` before anyone has signed in. |
| `DEALGO_DATA_DIR` | `./data` (`/data` in Docker) | Where the database and your own plugins live. |
| `DEALGO_DATABASE_URL` | SQLite in the data dir | Any SQLAlchemy URL. Only SQLite is tested — see note below. |
| `DEALGO_HOST` | `0.0.0.0` | Listen address inside the container. |
| `DEALGO_PORT` | `8080` | Listen port inside the container. |
| `DEALGO_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `TZ` | `UTC` | Container time zone, for log timestamps. Schedules are always UTC. |

Compose-only (used by `docker-compose.yml`, not by the app):

| Variable | Default | Meaning |
| --- | --- | --- |
| `DEALGO_BIND` | `0.0.0.0:8080` | Host side of the published port. `127.0.0.1:8080` keeps it local. |
| `DEALGO_IMAGE` | `dealgo:latest` | Image to run, e.g. from a registry. |
| `DEALGO_DATA` | `dealgo-data` | Named volume or absolute host path for `/data`. |
| `DEALGO_MEMORY_LIMIT` | `512M` | Container memory limit. |

Put them in `.env` beside `docker-compose.yml`. It is gitignored.

**Database note:** other databases are not tested, and at least one column is too narrow for
PostgreSQL's strict length checks. Use SQLite.

**Related:** [Installing](Installing.md) · [Running in Production](Running%20in%20Production.md)

## Renamed

`DEALGO_CLIENT_ID`, `DEALGO_CLIENT_SECRET` and `DEALGO_API_KEY` are no longer read: they are the
YouTube plugin's settings now. The first start after upgrading copies any values they held, and any
the Settings page held, into the plugin's settings for everyone, and says so in the log. Rename them
to `DEALGO_PLUGIN_YOUTUBE_CLIENT_ID` and so on, or remove them and use the plugin's card.
