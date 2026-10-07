# Settings

Each account has its own Settings.

## Theming

**Change the look** opens [Theming](Theming.md). It covers your colours by day and by night,
typefaces, text size, corners, spacing, shadows and the focus ring, with a live preview and a
contrast check. Only you see your theme.

## AI model

**Choose a model** opens the page a [Text box](Nodes/Text.md) writes with. Each account chooses its
own:

| Kind | Model | Address | Key |
| --- | --- | --- | --- |
| **Claude, from Anthropic** | Blank for `claude-opus-5-5`, or another Claude model's name | Blank, unless you go through a proxy | From the [Anthropic Console](https://console.anthropic.com/) |
| **OpenAI** | The model's name | Blank | Your OpenAI key |
| **An open-weight model on a server of your own** | The name your server knows it by, e.g. `llama3.1` | The server's address ending in `/v1`, e.g. `http://localhost:11434/v1` for Ollama | Usually none |

The third kind is any server that speaks the OpenAI chat API: Ollama, vLLM, LM Studio and others.
From inside the Docker container, a server on the same machine is at `host.docker.internal` rather
than `localhost`.

The key is kept for your account only. It is never shown again — leave the field blank to keep it,
or tick **Forget the saved key** — and it is not in backups. **Ask it** asks the saved model for one
sentence, to know it answers. Claude and OpenAI charge your account with them for what is read and
written.

## Your algorithm

Also on the AI model page: an algorithm of your own, which an [Aggregation](Nodes/Aggregation.md)
piece puts to work. **Learn from how I watch in Focus mode** turns it on or off — off, Focus mode
remembers nothing. Choose how many days back it learns from, how many items it needs before it says
anything, and whether it learns again every run or once a day. For each of interest, retention and
engagement, the page shows how many items it learned from, how well it did on items it was not
shown, and what it leans towards and away from. **Learn now** and **Forget everything** do what they
say.

## Plugins

A folded block for each plugin that has something for you: a service to sign in to, or settings each
account sets for itself. Click one to open it. Each is marked with the plugin's badge and colour, the same as on its card
under Admin → Plugins. Your values and sign-ins are yours; changing them changes nothing for anyone
else. Plugins the admin has switched off are not listed.

**Signing in.** A plugin that writes back to its service as you — YouTube, filling playlists — has
**Connect … account**, **Reconnect** after a grant expires, and **Disconnect**. Disconnecting keeps
your history and stops writing to that service. Where the service has a daily allowance, the block
shows how much of it is spent today, for everyone on this De-Algo. See
[Connecting YouTube](Connecting%20YouTube.md) and [Quota](Quota.md).

**Feeds on YouTube.** The plugin feeds are published through (YouTube) also has a section for
making a feed backed by a new or existing playlist on that service. Needs a connected account. See
[Feeds](Nodes/Feeds.md).

Settings that apply to everyone, such as a plugin's OAuth client, are the admin's, on the plugin's
card under Admin → Plugins.

## Back up your setup

Download or load a setup file. See [Backup and Restore](Backup%20and%20Restore.md) — and read what it
does not include.

## Fixed values

These used to be settings and now keep their defaults:

| Value | Default |
| --- | --- |
| How often De-Algo wakes to check [triggers](Nodes/Triggers.md) | 30 minutes |
| Items taken from a new source when no backfill is given | 3 |

**Related:** [Accounts](Accounts.md) · [Quota](Quota.md)
