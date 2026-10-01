# Command Line

The same program runs headless, for cron and shells. In Docker, prefix each command with
`docker compose run --rm dealgo`, or use the `make` shortcut.

| Command | `make` shortcut | Does |
| --- | --- | --- |
| `dealgo serve` | `make up` | Run the web app. The default. |
| `dealgo sync` | `make sync` | One run for every account, then exit. |
| `dealgo sync --force` | `make sync FORCE=1` | The same, checking every source whatever its triggers say. |
| `dealgo add <reference>` | `make add CHANNEL=…` | Start watching a source. |
| `dealgo channels` | `make channels` | List watched sources. |
| `dealgo watched <id or URL> …` | `make watched VIDEO="…"` | Mark videos watched. |
| `dealgo remove-watched` | `make remove-watched` | Remove watched items from feeds. |
| `dealgo export [-o FILE]` | `make backup` | Write a [setup file](Backup%20and%20Restore.md). |
| `dealgo status` | `make info` | Show configuration. |
| `dealgo --version` | | Print the version. |

`serve` takes `--host` and `--port`.

## With sign-in on

Only `sync` and `serve` know about accounts. The other commands act on the space used when sign-in is
**off**, which is empty once an admin is set. Use the web app for them instead.

**Related:** [Triggers](Triggers.md) · [Accounts](Accounts.md)
