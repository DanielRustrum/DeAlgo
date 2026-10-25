# Connecting an Account

Optional. Pamphlets reads every source without signing in anywhere. An account is only needed for a
plugin that **writes back** to its service as you — filling a playlist there, say, or reading
details its public feed leaves out.

How that works is the plugin's: it says which service it signs in to and what it asks for (see
[Signing In](Creating%20A%20Plugin/Signing%20In.md)). The admin registers Pamphlets with that service
once, for the whole install; then each account signs in with its own account there.

## The admin: register Pamphlets with the service

1. In the service's developer console, register an OAuth client of type **Web application** (the
   plugin's own instructions say where, and which API to enable).
2. Add an **authorized redirect URI**: your `PAMPHLETS_PUBLIC_URL` plus `/oauth/callback`, e.g.
   `http://localhost:8080/oauth/callback`. It must match character for character. The plugin's
   card under **Admin → Plugins** shows the exact string, with a copy button.
3. On that card, under **Settings for everyone**, enter the client id and secret, and whatever else
   the plugin asks for. They can also come from the environment, as
   `PAMPHLETS_PLUGIN_<PLUGIN>_<SETTING>` — see [Environment Variables](Environment%20Variables.md).

## Each account: sign in

Under **Settings → Plugins**, the plugin's block has **Connect** with the name of the account it
signs in to. The grant is kept, so you do this once.

## Making a feed that writes to the service

Feeds you drag onto the canvas live inside Pamphlets. A plugin that publishes adds a section to its
block under **Settings → Plugins** for feeds backed by the service — a new one there, or one you
already have. See [Feeds](Nodes/Feeds.md).

## If the service refuses the sign-in

- **A redirect URI mismatch** — the redirect URI is missing or differs. Check it is listed as an
  *authorized redirect URI*, not a *JavaScript origin*, and that the client type is **Web
  application**.
- **Access denied, or "not verified"** — many services keep a new client in a testing mode that
  only admits listed test users. Add your own account there, or publish the client.

## When a grant ends

Some services expire a grant after a while, especially while the client is in testing. When one
dies, Pamphlets says so in the plugin's block under Settings, and as a toast on every page: the
plugin's own words, with a link to reconnect. The same toast asks an account that has never signed
in to connect, and tells everyone when the admin hasn't set up the client yet. Only the admin's
toast links to where that is done. Dismissing a toast lasts the browsing session; it comes back
while the condition holds. Items keep collecting inside Pamphlets and are written to the service
after you reconnect.

## Without an account

Everything still works. Feeds backed by the service are marked *local only* and collect inside
Pamphlets; what they collect is written there after you connect, as [quota](Quota.md) allows.

**Related:** [Quota](Quota.md) · [Feeds](Nodes/Feeds.md) · [Settings](Settings.md)
