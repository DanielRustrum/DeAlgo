# Sources

A source kind teaches De-Algo to recognise a kind of reference — `r/python`, `@name.bsky.social` —
and where its feed is. De-Algo fetches and parses the feed (RSS or Atom); your plugin only says what is
particular about it.

Each kind becomes a box under **Plugins** in the palette.

## Declaring one

```lua
sources = {
  {
    kind = "example",                       -- required; a-z 0-9 - _ ; 12 characters or fewer
    label = "Example",                      -- the service's name
    noun = "Example account",               -- what its box is called
    example = "@name, or https://example.com/@name",   -- shown in the empty box
    blurb = "One account. Everything it posts.",        -- shown in the palette
    colour = "jade",                        -- its boxes' colour, from the list below
    playlistable = false,                   -- true only if items can go in a YouTube playlist

    recognise = function(reference) … end,  -- required
    accept    = function(typed) … end,      -- optional
    refine    = function(item) … end,       -- optional
    home      = function(key) … end,        -- optional
    item_url  = function(key, link) … end,  -- optional
    mirror    = function(key) … end,        -- optional
    posts     = function(key) … end,        -- optional
  },
},
```

## colour

What the source's boxes wear on the canvas: the bar down the box, its palette row, and the pills that
name it. Pick one of these, or leave it out for green. `color` works too.

`green` (the default) · `moss` · `jade` · `sky` · `pink` · `red` · `slate`

Only these, because each is drawn for both light and dark themes, and none is a colour the canvas
already uses for another kind of box: violet triggers, amber filters, blue sorts, teal stamps, brown
repositories, terracotta feeds. Anything else stops the plugin loading, with a message listing the
allowed names. The shipped plugins use `red` (YouTube) and `sky` (Bluesky).

## recognise(reference) — required

Called with whatever somebody typed or pasted, asking every plugin in turn. Return a table if it is
yours, or `nil`.

| Field | Required | Meaning |
| --- | --- | --- |
| `key` | **yes** | What identifies it within your kind, e.g. `@ann`. Stored as the source's id; unique per account. |
| `feed` | **yes** | The address of its RSS or Atom feed. |
| `title` | no | A name until the feed supplies its own. Defaults to `key`. |
| `guess` | no | `true` if you are offering rather than asserting. Any certain answer beats every guess. |

```lua
recognise = function(reference)
  local name = string.match(reference, "^https?://example%.com/@([%w_]+)/?$")
  if name then
    return { key = "@" .. name, feed = "https://example.com/@" .. name .. ".rss", title = "@" .. name }
  end
  -- "@name" might be ours, or another service's handle: offer, don't assert.
  name = string.match(reference, "^@([%w_]+)$")
  if name then
    return { key = "@" .. name, feed = "https://example.com/@" .. name .. ".rss",
             title = "@" .. name, guess = true }
  end
  return nil
end,
```

Be strict. `recognise` is asked about references meant for other plugins; claiming them breaks those.

## accept(typed)

Called instead of `recognise` when the text was typed into **your** box, so the kind is already
settled and a bare `ann` can be yours. Same return value. Without `accept`, `recognise` is used.

## refine(item)

Called for every entry read from your source's feed. Return only what you want to change.

| `item` field | Meaning |
| --- | --- |
| `guid` | The entry's id in the feed |
| `title` | Its title |
| `link` | Its link |
| `summary` | Its text or description |

| Return field | Meaning |
| --- | --- |
| `id` | The item's identity, used to recognise it next time. **Must be unique across every source an account has** — prefix it, e.g. `example-42`. Omit to let De-Algo hash the guid. |
| `kind` | `"link"` (default), `"post"`, or `"video"`. Use `"video"` only for a YouTube video id: Focus mode plays those in YouTube's player. |
| `is_short` | `true` for a YouTube Short. |

## home(key) and item_url(key, link)

Where the source itself lives, and where one of its items lives. Used for the **↗** links. Return a
URL string, or `nil` to use the feed's own link.

## mirror(key)

A second address serving the same feed, offered when your source rate-limits readers. It is shown as a
suggestion in the source's panel; De-Algo uses a mirror only after the person sets it, and only when
the source itself refuses.

## posts(key)

For content your source publishes but its feed does not carry. Called on every check, after the feed.
Return a list of up to 200 rows:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | **yes** | Unique across all sources, as for `refine`. Rows without one are dropped. |
| `text` | no | The words. Its first line becomes the title. |
| `images` | no | A list of image URLs. The first becomes the thumbnail. |
| `published_at` | no | Seconds since 1970 (UTC). |

Posts are subject to the source's backfill on its first check. Usually needs the `network`
permission to fetch something — see [Network](Network.md). YouTube's community posts work this way.

## When hooks run

| Hook | Runs | `dealgo` and `account` answer? |
| --- | --- | --- |
| `recognise`, `accept` | When somebody adds a source | No |
| `refine`, `posts` | On every check of the source | `posts` only |
| `home`, `item_url`, `mirror` | When pages are drawn | No |

See [The dealgo Object](The%20dealgo%20Object.md) for why.

## Items that cannot go everywhere

A source with `playlistable = false` (the default) can only fill feeds that live in De-Algo; items
reaching a YouTube-backed feed are skipped with a reason. Only YouTube is playlistable.

**Related:** [Augmentations](Augmentations.md) · [Network](Network.md) · [Plugin Files](Plugin%20Files.md)
