# Sources

A source kind teaches Pamphlets to recognise a kind of reference — `r/python`, `@name.bsky.social` —
and where its feed is. Pamphlets fetches and parses the feed (RSS or Atom); your plugin only says what is
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
    item_url  = function(key, link, kind) … end,  -- optional
    takes     = { … },                      -- optional: kinds of content, each a switch
    classify  = function(item) … end,       -- required with `takes`
    mirrors   = false,                      -- optional: never offer a mirror address
    player    = "youtube",                  -- optional: Focus mode's built-in player for its videos
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
allowed names. The YouTube plugin uses `red`, and the Bluesky plugin `sky`.

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
| `id` | The item's identity, used to recognise it next time. **Must be unique across every source an account has** — prefix it, e.g. `example-42`. Omit to let Pamphlets hash the guid. |
| `kind` | `"link"` (default), `"post"`, or `"video"`. Use `"video"` only for a YouTube video id: Focus mode plays those in YouTube's player. |
| `hint` | Up to 16 characters about what it is, kept with the item and handed to your `classify` later. YouTube says `"shorts"` for an entry linked as a Short. |

## home(key) and item_url(key, link, kind)

Where the source itself lives, and where one of its items lives. Used for the **↗** links. `kind` is
the item's own (`"video"`, `"post"` or `"link"`), for a source whose items live at different
addresses. Return a URL string, or `nil` to use the feed's own link.

## takes and classify(item)

For a source that publishes more than one kind of thing, where people want some and not others.
YouTube's:

```lua
takes = {
  { name = "videos", label = "Videos" },
  { name = "shorts", label = "Shorts", off = true },          -- off for a new source
  { name = "live", label = "Live", off = true },
  { name = "posts", label = "Posts", extras = true },          -- comes from `posts`
},
classify = function(item)
  if item.kind == "post" then return "posts" end
  if item.live == "live" or item.live == "upcoming" then return "live" end
  if item.hint == "shorts" then return "shorts" end
  return "videos"
end,
```

Each kind becomes a switch on the source's box. `classify` is handed the item (the same fields an
[augmentation](Augmentations.md#what-an-item-looks-like) gets) and returns one of the names; an item
it cannot place is let through. It runs for the account whose item it is, so it can read that
account's [settings](Settings.md) — what counts as a Short is a YouTube user setting. A held item's
reason is the kind's `label`, which is how switching it back on finds what it held. When every kind
marked `extras` is switched off, `posts` is not called at all.

Without `takes`, the source takes everything and its box says so.

## player

Which of Focus mode's built-in players plays this source's items of kind `"video"`. Only `"youtube"`
exists. Without one, every item is read rather than played: shown with its pictures and text and a
link out. A player is browser code that runs with the signed-in person's session, so it cannot be a
plugin's own; anything not on the list stops the plugin loading.

## view(item, settings), act and style

How one of your items looks when it is opened in [Focus mode](../Focus%20Mode.md), instead of
Pamphlets's own pictures-and-words layout. `view` answers **XML**, made of the components below;
`style` is **CSS** to dress them; `act` answers a form in the view.

![A plugin's own layout for a recipe in Focus mode](../images/focus.png)

```lua
style = [[
  heading { color: var(--accent); }
  .score { font-weight: bold; }
  row { gap: 16px; }
]],
view = function(item, settings)
  return '<view>'
    .. '<heading level="1">' .. item.title .. '</heading>'
    .. '<row><image src="' .. (item.images[1] or "") .. '" alt=""/>'
    ..   '<paragraph>' .. item.words .. '</paragraph></row>'
    .. '<form><label>Rate it <input name="score" type="range" min="1" max="5"/></label>'
    ..   '<button>Rate</button></form>'
    .. '</view>'
end,
act = function(item, values, settings)
  return '<view><text class="score">You gave it ' .. values.score .. '</text></view>'
end,
```

**The item** is a table of `title`, `kind`, `words`, `link`, `images` (a list), `thumbnail`,
`duration`, `views`, `likes`, `published` (ISO 8601), `author` (the source's name), `source` (its
kind), `key`, `tags` (a list) and `hint`.

**Components.** Anything else is dropped — what is written inside it is kept, as text — and so is
any attribute not listed. Every component also takes `class` and `title`.

| Component | Becomes | Attributes |
| --- | --- | --- |
| `view`, `box`, `column` | A stack | |
| `row` | Side by side, wrapping | |
| `grid` | A grid of equal cells | |
| `spacer`, `divider`, `break` | Space; a rule; a line break | |
| `heading` | A heading | `level`, 1–4 |
| `text`, `paragraph` (`p`), `strong`, `em`, `small`, `code`, `pre`, `quote`, `badge` | Words | |
| `link` | A link, opening in a new tab | `href` |
| `image` | A picture | `src`, `alt`, `width`, `height` |
| `video`, `audio` | The browser's player | `src`, `poster`, `loop`, `muted` |
| `embed` | A YouTube or Vimeo player, or a video file | `src` |
| `list` and `item` | A list | `ordered` on `list` |
| `table`, `table-row`, `cell`, `header-cell` | A table | `span` on cells |
| `details` and `summary` | A part that opens and closes | `open` |
| `progress` | A bar | `value`, `max` |
| `form`, `label`, `input`, `textarea`, `select`, `option`, `button` | A form | `name`, `type` (text, number, date, email, url, checkbox, radio, range, color, time, hidden), `value`, `placeholder`, `min`, `max`, `step`, `required`, `pattern`, `checked`, `rows`, `selected`; `href` on a `button` makes it a link |

Addresses — `href`, `src`, `poster` — are kept only if they start `http://` or `https://`. Up to
200 KB of XML; no `DOCTYPE` or entities.

**CSS.** Write selectors with the components' names — `heading`, `row`, `badge` — or your own
classes. Every rule is scoped to your view and reaches nothing outside it. `@media`, `@supports` and
`@keyframes` are kept; every other at-rule is dropped, and so is any declaration with
`expression(`, `javascript:` or a `url(…)` that is not `https://` or an image `data:` address. The
theme's variables — `var(--accent)`, `var(--text)`, `var(--panel)` — follow the person's theme.

**Forms.** A `form` in the view is sent to `act(item, values, settings)`, `values` being its fields
by name. Answer the view as it should look now; it replaces the old one. Without `act`, a form does
nothing.

`view` and `act` run for the account whose item it is: `pamphlets.sources()`,
`pamphlets.queue(name)` and the rest answer about it, with the permissions granted. One that throws
or answers XML that cannot be read leaves the item in Pamphlets's own layout, with the reason above it.

## mirror(key)

A second address serving the same feed, offered when your source rate-limits readers. It is shown as a
suggestion in the source's panel; Pamphlets uses a mirror only after the person sets it, and only when
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

| Hook | Runs | `pamphlets` and `account` answer? |
| --- | --- | --- |
| `recognise`, `accept` | When somebody adds a source | No |
| `refine`, `posts` | On every check of the source | `posts` only |
| `home`, `item_url`, `mirror` | When pages are drawn | No |
| `view`, `act` | When one of its items is opened in Focus mode, and when a form in it is sent | Yes |

See [The pamphlets Object](The%20pamphlets%20Object.md) for why.

## Items that cannot go everywhere

A source with `playlistable = false` (the default) can only fill feeds that live in Pamphlets; items
reaching a YouTube-backed feed are skipped with a reason. Only YouTube is playlistable.

**Related:** [Augmentations](Augmentations.md) · [Network](Network.md) · [Plugin Files](Plugin%20Files.md)
