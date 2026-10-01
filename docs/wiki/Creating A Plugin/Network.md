# Network

With the `network` permission, a plugin gets a `net` object.

## net.get(url, headers)

Fetches a page and returns its text, or `nil` if it could not.

```lua
local html = net.get("https://example.com/@ann", { ["User-Agent"] = "Mozilla/5.0" })
if not html then return {} end
```

- `http://` and `https://` only.
- At most **4 requests per call** into your plugin, and **2 MiB** per response. Beyond either, `nil`.
- Only these headers may be set: `User-Agent`, `Accept`, `Accept-Language`, `Referer`. Others are dropped.
- Never errors: a failure returns `nil` and is logged.
- Requests go through De-Algo, which honours rate limits a site has announced. If a site has asked
  De-Algo to wait, `get` returns `nil` rather than asking again.

Remember the caution the admin sees: anything your plugin has been shown could leave the machine
through `net.get`. Fetch only what you said you would.

## net.embedded(text, name, key)

Many pages keep their data in a JSON object assigned to a script variable. This finds every value
under `key`, at any depth, inside the object assigned to `name` — without parsing a megabyte of JSON in
Lua.

```lua
local html = net.get("https://example.com/@ann/posts")
local found = net.embedded(html, "ytInitialData", "postRenderer")   -- a list, or nil
for _, post in ipairs(found or {}) do
  -- post is a Lua table
end
```

Returns `nil` if the variable is not found, otherwise a list (possibly empty), outermost match first,
of at most 500 matches.

## net.find(thing, key)

The same search over a table you already have — for looking inside one of `embedded`'s results.

```lua
local images = net.find(post, "thumbnails")
```

## Not available

There is no way to send a body, use other methods, set cookies or read response headers. For signed
requests to Google, see [Account](Account.md).

**Related:** [Permissions](Permissions.md) · [Sources](Sources.md)
