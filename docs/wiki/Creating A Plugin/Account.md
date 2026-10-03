# Account

With the `account` permission, a plugin gets an `account` object for calling its own service **as the
signed-in account** — without ever seeing the credential. De-Algo attaches the token, sends the
request, and charges the service's daily allowance.

It needs a [`connect`](Signing%20In.md) table: that says how the service signs people in, and which
**hosts** the token may be sent to. `send` refuses every other address.

## account.connected()

`true` if the running account has signed in to the plugin's service, or the admin set an API key.
Check it before doing work that needs one.

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
| `url` | An `https://` address on one of `connect.hosts` (or a subdomain), query string included |
| `body` | A table, sent as JSON; `nil` for none |
| `cost` | Units of the service's allowance this call costs, `1`–`100`. Default `1`. |

Returns the response's JSON as a table, `{}` for an empty response, or `nil` on any failure
(refused, unreachable, not signed in). A JSON list comes back as `{ items = list }`. Failures are
logged with the reason `connect.refusal` reads out of the answer.

## Limits and charging

- At most **30 signed calls** per call into your plugin.
- Responses over **4 MiB** come back empty.
- The cost is charged **whether or not the service accepted the request**, since services that ration
  usually charge for refusals too — except a refusal whose reason is `connect.allowance.exhausted`,
  which marks the day as spent instead.
- With only an API key and no sign-in, the key is sent as `?key=` instead: reads work, writes fail.

## When it answers

Only while De-Algo is working for an account — see [The dealgo Object](The%20dealgo%20Object.md#whose-account).
Otherwise `connected()` is `false` and `send` returns `nil`.

**Related:** [Signing In](Signing%20In.md) · [Publishing](Publishing.md) · [Permissions](Permissions.md)
