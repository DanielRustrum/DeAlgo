# Account

With the `account` permission, a plugin gets an `account` object for calling Google's APIs **as the
connected account** — without ever seeing the credential. De-Algo attaches the token, sends the
request, and charges the account's [quota](../Quota.md).

**Only Google hosts can be signed for:** `googleapis.com`, `www.googleapis.com` and
`youtube.googleapis.com`. This capability exists for the YouTube plugin and services like it.

## account.connected()

`true` if the running account has a Google grant or an API key. Check it before doing work that needs one.

## account.send(method, url, body, cost)

```lua
local page = account.send("GET",
  "https://www.googleapis.com/youtube/v3/channels?part=snippet&id=UC…", nil, 1)
if not page then return {} end
for _, item in ipairs(page.items or {}) do … end
```

| Argument | Meaning |
| --- | --- |
| `method` | `"GET"`, `"POST"`, `"PUT"` or `"DELETE"` |
| `url` | An `https://` address on a Google host, query string included |
| `body` | A table, sent as JSON; `nil` for none |
| `cost` | Quota units this call costs, `1`–`100`. Default `1`. |

Returns the response's JSON as a table, `{}` for an empty response, or `nil` on any failure
(refused, unreachable, not signed in). A JSON list comes back as `{ items = list }`. Failures are
logged with Google's reason.

## Limits and charging

- At most **30 signed calls** per call into your plugin.
- Responses over **4 MiB** come back empty.
- The cost is charged **whether or not Google accepted the request** — Google charges for refused
  requests too — except when Google refused it for lack of quota.
- With only an API key and no grant, the request is sent with the key instead: reads work, writes fail.

## When it answers

Only while De-Algo is working for an account — see [The dealgo Object](The%20dealgo%20Object.md#whose-account).
Otherwise `connected()` is `false` and `send` returns `nil`.

**Related:** [Publishing](Publishing.md) · [Permissions](Permissions.md)
