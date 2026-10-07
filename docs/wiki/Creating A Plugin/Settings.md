# Settings

A plugin can ask to be configured. There are two kinds of setting, for two kinds of person:

| Kind | Set by | Where | For |
| --- | --- | --- | --- |
| `app` | The admin, once | On the plugin's card under **Admin → Plugins**, beside what it is allowed to do | The whole install: a server address, an API key the install pays for |
| `user` | Each account, for itself | Under **Settings → Plugins** | One person's preferences |

Settings need no permission. A plugin can only read its own, and `user` settings are only those of
the account whose work is being done.

## Declaring them

```lua
settings = {
  app = {
    { name = "server", label = "Server", default = "https://example.com",
      hint = "Where every account's feeds are read from." },
    { name = "token", label = "API token", type = "secret" },
    { name = "per_page", label = "Items per page", type = "number", default = 25 },
  },
  user = {
    { name = "show_replies", label = "Show replies", type = "toggle", default = false },
    { name = "language", label = "Language", type = "choice",
      choices = { "en", "de", { value = "fr", label = "Français" } } },
  },
},
```

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | **yes** | a-z, 0-9, `-` and `_`; unique within its kind. What you read it by. |
| `label` | no | What the form calls it. Defaults to the name. |
| `type` | no | `text` (default), `number`, `toggle`, `choice` or `secret`. |
| `default` | no | Its value until someone sets it. A `choice` defaults to its first option; a `toggle` to off. |
| `hint` | no | A line under the control. |
| `placeholder` | no | Shown in an empty text box. |
| `choices` | for `choice` | A list of strings, or of `{ value = …, label = … }`. |

A `secret` is never shown again once saved. Leaving its box empty keeps what is saved, and the form
offers to clear it.

Up to 20 settings of each kind. Anything malformed stops the plugin loading, and the Plugins page says
why: an unknown `type`, a choice with no choices, a default that is not a number or not one of the
choices.

## Reading them

```lua
local server = settings.app("server")          -- the admin's value, or the default
local replies = settings.user("show_replies")   -- this account's value, or the default
```

Values come back typed: `number` as a number, `toggle` as `true` or `false`, everything else as a
string. A name you never declared gives `nil`.

`settings.user` answers for the account whose work is in hand: during a sync, the account being
synced. Outside one, while a reference is being recognised for example, it gives the default.

## What happens to the values

They are kept in Pamphlets's database. They do not go into the plugin's folder, and they are not in
per-account backups or migration files. Removing the plugin removes its settings, both the admin's
and every account's. Switching it off keeps them, and the admin can still change the app settings
while it is off.
