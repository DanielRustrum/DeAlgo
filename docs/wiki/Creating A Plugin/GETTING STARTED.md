# Getting Started

A Pamphlets plugin is a Lua file that adds **kinds of source** (where items come from) and
**augmentations** (conditions and orderings that slot under Filter and Sort boxes). This page builds a
working plugin in five minutes. The rest of this folder is the reference.

## What a plugin can and cannot do

**It can** tell Pamphlets how to recognise a source and where its feed is, add to what Pamphlets reads
from that feed, judge or rank items, and — with permission — fetch pages, read the time, read and
change the running account's sources, and talk to Google as that account.

**It cannot** touch files, run programs, import modules or see the host. It runs in a sandbox with a
memory and time limit, and everything beyond pure Lua must be granted by the admin. Pamphlets does the
heavy lifting: it fetches and parses feeds, so your plugin never parses XML.

## 1. Make the folder

A plugin is a folder whose name is its id. Ids use `a-z`, `0-9`, `-` and `_`.

```
hackernews/
└── plugin.lua
```

## 2. Write `plugin.lua`

```lua
-- Hacker News: the front page as a source, and a condition for it.
return {
  name = "Hacker News",
  version = "1.0.0",
  api = 1,

  sources = {
    {
      kind = "hackernews",
      label = "Hacker News",
      noun = "Hacker News",
      example = "hn, or news.ycombinator.com",
      blurb = "The front page, as it changes.",

      -- Is this reference ours? Answer with where its feed is, or nil.
      recognise = function(reference)
        local typed = string.lower(reference)
        if typed == "hn" or string.find(typed, "news.ycombinator.com", 1, true) then
          return {
            key = "hn",
            feed = "https://news.ycombinator.com/rss",
            title = "Hacker News",
          }
        end
        return nil
      end,
    },
  },

  augmentations = {
    {
      kind = "no-ask-hn",
      label = "No Ask HN",
      blurb = "Holds Ask HN threads.",
      -- Goes under a Filter, so it answers keep(item) with true or false.
      keep = function(item)
        if item.source ~= "hackernews" then return true end  -- not ours: let it by
        return string.find(item.title or "", "^Ask HN:") == nil
      end,
    },
  },
}
```

The file returns one table. Nothing in it runs by itself: Pamphlets calls the functions when it needs them.

## 3. Install it

As the admin, open **Admin → Plugins**:

- **Add one from a file** — upload `plugin.lua` renamed to `hackernews.lua` (the file name becomes the id), or
- **Add one from a repository** — push the folder to GitHub, GitLab, Codeberg or Gitea and paste its address.

Pamphlets shows what the plugin offers and asks for. This one asks for nothing. Confirm, and it loads at once.

## 4. Use it

On **Configuration**, open the palette. Under **Plugins → Hacker News** you will find:

- a **Hacker News** source box — drag it out, type `hn`, wire it to a feed and a trigger, and switch it on;
- a **No Ask HN** condition — slot it under a Filter on that path.

Press **Test** on the trigger to see what would arrive, and which items No Ask HN holds back.

## 5. Iterate

Edit the file and add it again with the same name: it replaces the old one. If it fails to load,
its row on the Plugins page says why, with a line number.

## Next

| Page | Covers |
| --- | --- |
| [Plugin Files](Plugin%20Files.md) | Folder layout, the returned table, ids, loading and errors |
| [The Sandbox](The%20Sandbox.md) | Which Lua you get, limits, and how values cross over |
| [Sources](Sources.md) | `recognise`, `accept`, `refine`, `posts` and the other source hooks |
| [Augmentations](Augmentations.md) | Conditions (`keep`) and orderings (`rank`), with settings fields |
| [Settings](Settings.md) | Settings the admin sets for everyone, and settings each account sets for itself |
| [Signing In](Signing%20In.md) | Letting each account sign in to your service, and its daily allowance |
| [Permissions](Permissions.md) | Asking for more than pure Lua |
| [The dealgo Object](The%20dealgo%20Object.md) | Reading and changing the running account's setup |
| [Network](Network.md) | Fetching pages and pulling JSON out of them |
| [Clock and Log](Clock%20and%20Log.md) | The time, and writing to the log |
| [Account](Account.md) | Calling Google as the connected account |
| [Publishing](Publishing.md) | Writing items back into the service, e.g. playlists |
| [Distributing](Distributing.md) | Publishing your plugin in a git repository |
| [Testing and Debugging](Testing%20and%20Debugging.md) | Finding out why it does not work |

The five plugins that ship with Pamphlets are complete examples, in `dealgo/plugins/builtin/`, each split
into a file per job: `plugin.lua` says who it is and requires the rest. Start with `reddit/` (a source
with a mirror and two conditions: `references.lua`, `source.lua`, `conditions.lua`) and `shape/`
(conditions and an ordering, no source). `youtube/` is the full set: sign-in, settings, a Data API
client and a publisher, each in its own file.
