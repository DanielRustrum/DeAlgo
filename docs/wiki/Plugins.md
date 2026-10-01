# Plugins

Plugins add kinds of [source](Sources.md) and [conditions](Filter.md) to everyone's palette. They are
written in Lua and run inside a sandbox. Managing them is **admin only**: **Admin → Plugins**.

Five ship with De-Algo: **YouTube**, **Reddit**, **Bluesky**, **Substack** and **Shape**.

## The list

Each row shows:

- **shipped** or **yours**, its version, and where it was fetched from;
- the source kinds it provides and the permissions it asked for, granted or not;
- how many of your sources depend on it;
- why it did not load, if it did not.

## Adding one

**From a repository** — paste a GitHub, GitLab, Codeberg or Gitea address, and optionally a branch or
tag. De-Algo downloads the repository's archive over HTTPS; nothing is cloned or run. It looks for
`plugin.lua` at the top or one folder down.

**From a file** — upload a `.lua` file. Its name becomes the plugin's id.

Either way, nothing is installed yet. You see what it offers and what it asks to be allowed to do,
and tick the permissions you grant. Only then is it written to disk. A plugin that will not load is
never kept.

## Permissions

A plugin can do nothing outside its own code unless granted:

| Permission | Allows |
| --- | --- |
| **Make network requests** | Fetch web pages, through De-Algo, capped in size and number. Anything it has seen could be sent elsewhere. |
| **Read the time** | Know the current time. |
| **See what you are watching** | Read the running account's sources and feeds. Never what you watched, never another account's. |
| **Change what you are watching** | Add a source (always paused) or switch one on or off, for the running account. |
| **Act as your connected account** | Send requests to Google as your account, charged to your quota. It never sees the credential. |
| **Write to the log** | Write lines to De-Algo's log. |

Untick any you would rather it did without — it still loads, and simply finds that ability missing.
Change them later on its row. Shipped plugins start with what they asked for; you can revoke it.

## Switching one off

**Switch off** stops a plugin offering anything. Sources of its kind keep polling their stored feed
address, but no new ones can be added and its conditions stop narrowing. The page warns when sources
depend on it.

A switched-off plugin also releases its source kind, so a replacement can take it over.

## Updating and removing

- **Update** — on a plugin fetched from a repository: fetches it again and asks for consent again.
- **Remove** — on your own plugins only. Shipped ones come back on the next start; switch them off instead.

## Replacing a shipped plugin

Add your own with the same id — the same file or folder name, e.g. `youtube`. Yours is used instead,
and the row says so.

## Where they live

Yours are in the data folder: `/data/plugins/<id>/plugin.lua` in Docker. A plugin placed there by hand
is read when De-Algo next starts.

**Writing one:** see [Creating A Plugin](Creating%20A%20Plugin/GETTING%20STARTED.md).

**Related:** [Sources](Sources.md) · [Filter](Filter.md) · [Accounts](Accounts.md)
