# Distributing

Publish a plugin in a public git repository and the admin of any Pamphlets can install it from
**Admin → Plugins → Add one from a repository**.

## Repository layout

Put `plugin.lua` at the top of the repository, or one folder down:

```
pamphlets-plugin-hackernews/          pamphlets-plugins/
├── plugin.lua                     ├── README.md
├── README.md                      └── hackernews/
└── LICENSE                            ├── plugin.lua
                                       └── README.md
```

If there are several, the shallowest `plugin.lua` is used.

## The plugin's id

Taken from the **repository's** name, lowercased: `pamphlets-plugin-`, `pamphlets-` or `plugin-` is removed
from the front, and anything other than letters, digits, `-` and `_` becomes `-`. So
`pamphlets-plugin-hackernews` installs as `hackernews`. Keep the id stable: conditions people have placed
are stored against it.

## Hosts

| Address | Fetched from |
| --- | --- |
| `https://github.com/<owner>/<repo>` | GitHub's archive |
| `https://<host>/<owner>/<repo>` | `/archive/<ref>.tar.gz` — GitLab, Gitea, Forgejo, Codeberg |
| `https://…/something.tar.gz` | That archive, as given |

HTTPS only, public repositories only. The admin can name a branch or tag; otherwise `main`, then
`master`, is tried. **Tag your releases** so admins can pin one.

## What is kept

Only `.lua`, `.md`, `.txt`, `.json` and `.toml` files, and `LICENSE`, `LICENCE`, `COPYING` and
`NOTICE`, up to three folders deep beside `plugin.lua`. Links, scripts and binaries are dropped.
Nothing is ever executed by fetching; `plugin.lua` and the `.lua` files it requires run only in the
sandbox.

Limits: 2 MiB to download, 8 MiB unpacked, 200 files.

## Installing and updating

The admin sees what the plugin offers and the permissions it asks for, and ticks what to grant. The
fetched files wait aside until they confirm — what was reviewed is exactly what is installed.

Pamphlets remembers where it came from. **Update** on the plugin's row fetches it again from the same
branch or tag and asks for consent again.

## Good practice

- Write a clear `why` for every permission. It is the admin's only basis for deciding.
- Ask for as little as possible, and work without what you are not granted.
- Let items from other sources through in your conditions.
- Bump `version` with each release; it is shown on the Plugins page.

**Related:** [Plugin Files](Plugin%20Files.md) · [Permissions](Permissions.md)
