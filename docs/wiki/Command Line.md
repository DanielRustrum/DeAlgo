# Command Line

The same program runs headless, for cron and shells. In Docker, prefix each command with
`docker compose run --rm pamphlets`, or use the `make` shortcut.

| Command | `make` shortcut | Does |
| --- | --- | --- |
| `pamphlets serve` | `make up` | Run the web app. The default. |
| `pamphlets sync` | `make sync` | One run for every account, then exit. |
| `pamphlets sync --force` | `make sync FORCE=1` | The same, checking every source whatever its triggers say. |
| `pamphlets add <reference>` | `make add CHANNEL=…` | Start watching a source. |
| `pamphlets channels` | `make channels` | List watched sources. |
| `pamphlets watched <id or URL> …` | `make watched VIDEO="…"` | Mark videos watched. |
| `pamphlets remove-watched` | `make remove-watched` | Remove watched items from feeds. |
| `pamphlets export [-o FILE]` | `make backup` | Write a [setup file](Backup%20and%20Restore.md). |
| `pamphlets status` | `make info` | Show configuration. |
| `pamphlets --version` | | Print the version. |

`serve` takes `--host` and `--port`.

## With sign-in on

Only `sync` and `serve` know about accounts. The other commands act on the space used when sign-in is
**off**, which is empty once an admin is set. Use the web app for them instead.

**Related:** [Triggers](Nodes/Triggers.md) · [Accounts](Accounts.md)
