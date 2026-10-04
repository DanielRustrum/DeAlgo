# Signing In

A plugin that writes back to its service as a person — YouTube filling a playlist — needs that
person's permission: an OAuth 2.0 sign-in. The plugin says how its service does it, in a `connect`
table; **De-Algo** does the sign-in, keeps the token, refreshes it, and attaches it to the plugin's
[`account.send`](Account.md) requests. The plugin never sees it.

## Declaring it

```lua
settings = {
  app = {
    { name = "client_id", label = "OAuth client id" },
    { name = "client_secret", label = "OAuth client secret", type = "secret" },
    { name = "api_key", label = "API key (optional)", type = "secret" },
    { name = "daily_quota", label = "Daily quota", type = "number", default = 10000 },
  },
},

connect = {
  name = "Google",                                         -- "Connect Google account"
  authorize = "https://accounts.google.com/o/oauth2/v2/auth",
  token = "https://oauth2.googleapis.com/token",
  revoke = "https://oauth2.googleapis.com/revoke",         -- optional
  scopes = { "https://www.googleapis.com/auth/youtube" },
  params = { access_type = "offline", prompt = "consent" },
  hosts = { "googleapis.com" },                            -- where the token may go
  client_id = "client_id", client_secret = "client_secret", api_key = "api_key",
  allowance = { daily = "daily_quota", reserve = 0, timezone = "America/Los_Angeles",
                unit = "units", exhausted = "quotaExceeded" },
  refusal = function(answer) … return reason end,           -- optional
  about = "A few sentences for the plugin's block under Settings.",
  notices = {                                                -- optional
    connect = "Connect your Google account so …",
    reconnect = "Google needs you to sign in again …",
    setup = "Writing needs an OAuth client, which the admin sets on this plugin's card.",
  },
},
```

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | **yes** | What the account is called: "Connect **Google** account". |
| `authorize`, `token` | **yes** | The service's consent page and token endpoint. `https://` only. |
| `revoke` | no | Where a token is revoked on disconnect. |
| `scopes` | no | Scopes to ask for, joined with spaces. |
| `params` | no | Extra query parameters for the consent page. De-Algo's own (`client_id`, `redirect_uri`, `response_type`, `scope`, `state`) always win. |
| `hosts` | **yes** | Host names the token may be sent to, and their subdomains. Up to 8. HTTPS only. |
| `client_id`, `client_secret` | no | Which of your **app settings** hold the OAuth client. Default `client_id` / `client_secret`; each must be declared in `settings.app`. |
| `api_key` | no | An app setting holding a key for reading before anyone signs in. Sent as `?key=`. |
| `allowance` | no | The service's daily budget, if it has one. `daily` and `reserve` are numbers or app setting names; `timezone` is when its day starts; `exhausted` is the refusal reason that means it is spent. |
| `refusal` | no | `function(answer)` returning why the service refused a request, read from its error JSON. |
| `about` | no | Shown in the plugin's block under Settings, beside the sign-in. |
| `notices` | no | What De-Algo shows as a standing toast while the account isn't ready, in your words. Each is up to 300 characters of plain text. `connect`: not signed in. `reconnect`: signed in, but the service wants it done again. `setup`: no OAuth client yet. De-Algo decides which applies, names your plugin, and adds the link: to the account's Settings, or for `setup` to your card under Admin, for the admin only. Any other key is refused. |

The OAuth client belongs to the admin, so it lives in your [settings](Settings.md) for everyone: the
admin enters it on your card under Admin → Plugins, where the redirect address to register with the
service is shown with a copy button. Each account then signs in under Settings → Plugins.

## The allowance

With an `allowance`, De-Algo keeps one count per day for the whole install, charges each
`account.send` its `cost`, and stops writing before the day's budget runs out (leaving `reserve` for
things done by hand). The count is shown in your block under Settings. Without one, nothing is held
back.

## Rules

- A `connect` that could not work — a missing address, an `http://` one, a host that is not a plain
  name, a setting name you did not declare, a time zone that does not exist — stops the plugin
  loading, with the reason on the Plugins page.
- The redirect URI is the same for every plugin: `DEALGO_PUBLIC_URL` plus `/oauth/callback`.
- Removing the plugin keeps accounts' tokens in the database but nothing uses them; signing out
  under Settings removes them.

**Related:** [Account](Account.md) · [Settings](Settings.md) · [Publishing](Publishing.md)
