-- The YouTube channel as a source: what it is called, what it publishes,
-- which kind each item is, and where things live.
--
-- The one source that can be written back to: a YouTube video may go into a
-- real YouTube playlist, and nothing else may. That is what `playlistable`
-- says, and the host refuses the wiring that would break it.

local references = require("references")
local posts = require("posts")

return {
  kind = "youtube",
  label = "YouTube",
  example = "@handle, a channel URL, or a UC… id",
  noun = "YouTube channel",
  blurb = "One channel. Uploads, and community posts if you want them.",
  -- Its boxes on the canvas, from the colours the app allows.
  colour = "red",
  playlistable = true,
  -- YouTube reads every channel's feed without complaint, so a second
  -- address for it is never worth offering.
  mirrors = false,
  -- Focus mode plays its videos in the YouTube player it has built in.
  player = "youtube",

  -- What a channel publishes, each a switch on its box. Shorts and
  -- broadcasts start switched off: most people follow a channel for its
  -- uploads. Posts come from the Posts tab, not the feed, so switching them
  -- off also stops that page being read.
  takes = {
    { name = "videos", label = "Videos" },
    { name = "shorts", label = "Shorts", off = true },
    { name = "live", label = "Live", off = true },
    { name = "posts", label = "Posts", extras = true },
  },

  -- Which of those one item is. A Short is one the feed linked as a Short,
  -- or one no longer than this account says a Short can be.
  classify = function(item)
    if item.kind == "post" then return "posts" end
    if item.live == "live" or item.live == "upcoming" then return "live" end
    local longest = settings.user("shorts_max_seconds") or 60
    if item.hint == "shorts" then return "shorts" end
    if item.duration and item.duration > 0 and item.duration <= longest then
      return "shorts"
    end
    return "videos"
  end,

  accept = references.accept,
  recognise = references.recognise,

  -- Where the channel itself lives, for a link out to it.
  home = function(channel_id)
    return "https://www.youtube.com/channel/" .. channel_id
  end,

  -- What the feed does not carry. Every other source here has one place
  -- its content lives; YouTube has two, and the second has no feed at all.
  posts = posts.read,

  -- Where an item lives: a video by its id, a post on its own page.
  item_url = function(id, link, kind)
    if kind == "post" then return "https://www.youtube.com/post/" .. id end
    if link and link ~= "" then return link end
    return "https://www.youtube.com/watch?v=" .. id
  end,

  -- What is YouTube's about a YouTube feed.
  --
  -- The feed is Atom and Pamphlets reads Atom already, so there is no second
  -- parser here — rewriting a namespace-aware XML reader as Lua string
  -- matching would be a worse parser, not a plugin. What is left is the part
  -- only YouTube knows: that an entry's id carries the video id, and that a
  -- Short is told apart by the address it links to and by nothing else
  -- without spending API quota.
  refine = function(item)
    local video = string.match(item.guid or "", "^yt:video:([%w_%-]+)$")
    local link = item.link or ""
    return {
      -- A video is filed under its own id, not under the feed's guid.
      id = video,
      kind = "video",
      -- A Short is linked as one; nothing else gives it away for free.
      hint = string.find(link, "/shorts/", 1, true) and "shorts" or nil,
    }
  end,
}
