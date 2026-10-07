# Connecting YouTube

Optional. Pamphlets reads every source — YouTube included — without any Google account. You only need
one to **write**: to fill real YouTube playlists, read video lengths and view counts, and look up
channels by `@handle`.

All of this is the YouTube plugin's. The admin gives it a Google OAuth client once, for the whole
install; then each account signs in with its own Google account.

## The admin: set up a Google OAuth client

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project and enable
   **YouTube Data API v3**.
2. Create an OAuth client of type **Web application**.
3. Add an **Authorized redirect URI**: your `DEALGO_PUBLIC_URL` plus `/oauth/callback`, e.g.
   `http://localhost:8080/oauth/callback`. It must match character for character. The YouTube
   plugin's card under **Admin → Plugins** shows the exact string, with a copy button.
4. On that card, under **Settings for everyone**, enter the client id and secret, and optionally an
   API key. They can also come from the environment: `DEALGO_PLUGIN_YOUTUBE_CLIENT_ID`,
   `DEALGO_PLUGIN_YOUTUBE_CLIENT_SECRET`, `DEALGO_PLUGIN_YOUTUBE_API_KEY`.

## Each account: sign in

Under **Settings → Plugins**, the YouTube block has **Connect Google account**. The grant is kept,
so you do this once.

## Making a feed that writes to YouTube

Feeds you drag onto the canvas live inside Pamphlets. To make one backed by a YouTube playlist, use
**Settings → Plugins → YouTube → Feeds on YouTube**: create a new playlist (choose private, unlisted or public) or adopt
one you already have. See [Feeds](Nodes/Feeds.md).

## If Google refuses the sign-in

- **`Error 400: redirect_uri_mismatch`** — the redirect URI is missing or differs. Check it is under
  *Authorized redirect URIs*, not *JavaScript origins*, and the client type is **Web application**.
- **`Error 403: access_denied`** / "has not completed verification" — the consent screen is in
  **Testing**, which only admits listed test users. Add your Google account under
  **OAuth consent screen → Audience → Test users**.

## Weekly reconnects

In **Testing** mode Google expires the grant after seven days. Publish the consent screen to stop
that. A personal app stays unverified, so Google shows an "unverified app" warning once —
choose *Advanced → Go to Pamphlets*.

When a grant dies, Pamphlets says so in the YouTube block under Settings, and as a toast on every
page: the plugin's own words, with a link to reconnect. The same toast asks an account that has
never signed in to connect, and tells everyone when the admin hasn't set up an OAuth client yet.
Only the admin's toast links to where that is done. Dismissing a toast lasts the browsing session;
it comes back while the condition holds. Items keep collecting inside Pamphlets and are written to
YouTube after you reconnect.

## Without an account

Everything still works. YouTube-backed feeds are marked *local only* and collect inside Pamphlets;
what they collect is written to the playlist after you connect, as [quota](Quota.md) allows.

**Related:** [Quota](Quota.md) · [Feeds](Nodes/Feeds.md) · [Settings](Settings.md)
