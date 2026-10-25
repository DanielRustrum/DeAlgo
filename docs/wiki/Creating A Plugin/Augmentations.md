# Augmentations

An augmentation is a piece users slot under one of Pamphlets's own boxes. A plugin can add three kinds:

| `under` | Box | Your function | Answers |
| --- | --- | --- | --- |
| `"filter"` (default) | Filter | `keep(item, settings)` | `true` to let the item through, `false` to hold it |
| `"sort"` | Sort | `rank(item, settings)` | A number; bigger comes first |
| `"transform"` | [Transform](../Nodes/Transform.md) | `transform(data, settings, params)` | What the Transform gives out, as JSON-like tables |

Each appears under **Plugins** in the palette, marked as an augmentation.

## Declaring one

```lua
augmentations = {
  {
    kind = "long-enough",                   -- required; a-z 0-9 - _
    label = "Long enough",                  -- shown on the piece and in the palette
    blurb = "Holds items shorter than a length you set.",
    fields = {
      { name = "minutes", label = "At least this many minutes", type = "number", default = "5" },
    },
    keep = function(item, settings)
      if item.duration == 0 then return true end          -- unknown is not short
      return item.duration >= (tonumber(settings.minutes) or 5) * 60
    end,
  },
  {
    kind = "by-likes",
    label = "Most liked",
    under = "sort",
    rank = function(item) return item.likes end,
  },
},
```

An augmentation under a filter without `keep`, under a sort without `rank`, or under a transform
without `transform`, stops the plugin loading. `under` must be `"filter"`, `"sort"` or
`"transform"`.

## Transformations

Under a Transform, `transform(data, settings, params)` is handed what comes into the Transform —
`data`, a list of rows, or one value; the piece's own fields as `settings`; and as `params` the
values the flow was [activated](../Nodes/Triggers.md#activation-and-activate) with (empty when it was
not). What it returns is what the Transform gives out:

```lua
{
  kind = "top-five",
  label = "Top five",
  under = "transform",
  fields = { { name = "by", label = "Most of", default = "views" } },
  transform = function(data, settings, params)
    table.sort(data, function(a, b) return (a[settings.by] or 0) > (b[settings.by] or 0) end)
    local out = {}
    for i = 1, math.min(5, #data) do out[i] = data[i] end
    return out
  end,
},
```

One that throws gives out nothing, and the error goes to the log. It runs for the account whose
Transform it is, so `pamphlets.sources()` and the rest answer about that account. A person can also
write a transformation of their own, in a [Lua piece](../Nodes/Transform.md#lua), with no plugin at
all.

## The item

| Field | Type | Meaning |
| --- | --- | --- |
| `source` | string | The source kind it came from, e.g. `"rss"`, or a plugin's own kind |
| `kind` | string | `"video"`, `"post"` or `"link"` |
| `title` | string | |
| `words` | string | Its text; `""` if none |
| `link` | string | |
| `duration` | number | Seconds; **`0` means unknown** |
| `views` | number | **`0` means unknown** |
| `likes` | number | **`0` means unknown** |
| `hint` | string | What its source's `refine` said about it; `""` if nothing |
| `live` | string | `"live"` or `"upcoming"` for a broadcast; `"none"`; `""` if unknown |

Lengths and counts are known only for items whose source gives them — some only once a plugin has
read their details as a signed-in account. Treat `0` as "nobody knows", not as "none" — otherwise
you will hold back everything from an account that has not connected.

## Judging only your own

A condition is slotted under a Filter that may carry items from any source. Unless your condition is
meant for every item, let other sources through:

```lua
keep = function(item)
  if item.source ~= "example" then return true end
  …
end,
```

## Settings fields

`fields` describes what the piece's panel asks. Each field:

| Key | Meaning |
| --- | --- |
| `name` | Required; `a-z 0-9 - _`. The key in `settings`. |
| `label` | Shown beside the input. |
| `type` | `"number"` or `"text"` (default). |
| `default` | Filled in when the piece is created. |
| `placeholder` | Shown when empty. |

`settings` holds the saved values **as strings**, keyed by `name`. A field may be missing or empty, so
always fall back: `tonumber(settings.minutes) or 5`.

## When things go wrong

- `keep` that errors, or returns anything but `false`, **lets the item through**.
- `rank` that errors, or returns something other than a number, places nothing: the item keeps its
  arrival order among others that could not be placed.

## When they run

`keep` runs as items are filed during a run, and in **Test**. `rank` runs as a batch is ordered. Both
run on an account's behalf, so [`pamphlets`](The%20pamphlets%20Object.md) and [`account`](Account.md) answer.

## Several on one Filter

All plugin conditions on a path must agree. See the user page [Filter](../Nodes/Filter.md).

**Related:** [Sources](Sources.md) · [The Sandbox](The%20Sandbox.md)
