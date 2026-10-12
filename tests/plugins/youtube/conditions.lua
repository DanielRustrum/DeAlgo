-- Conditions for the canvas: augmentations that slot under a Filter box and
-- narrow what comes past it. Each judges YouTube's own items and lets
-- everything else by untouched — a condition asking about view counts must
-- not swallow a subreddit that has none, and "no likes recorded" is not
-- "nobody liked it".
--
-- What kind of thing a YouTube item is lives here rather than in the host:
-- a Short, a premiere and a community post are YouTube's own distinctions,
-- and the host has no business knowing the difference.

return {
  {
    kind = "no-videos",
    label = "No videos",
    blurb = "Holds ordinary uploads.",
    keep = function(item)
      if item.source ~= "youtube" then return true end
      if item.kind ~= "video" then return true end
      -- A Short and a broadcast are their own things, each with a
      -- condition of its own. This one is about everything else.
      if item.hint == "shorts" then return true end
      if item.live == "live" or item.live == "upcoming" then return true end
      return false
    end,
  },

  {
    kind = "no-live",
    label = "No live",
    blurb = "Holds broadcasts, live or still to come.",
    keep = function(item)
      if item.source ~= "youtube" then return true end
      return not (item.live == "live" or item.live == "upcoming")
    end,
  },

  {
    kind = "no-posts",
    label = "No posts",
    blurb = "Holds community posts.",
    keep = function(item)
      if item.source ~= "youtube" then return true end
      return item.kind ~= "post"
    end,
  },

  {
    kind = "no-shorts",
    label = "No Shorts",
    blurb = "Holds Shorts on this path only.",
    keep = function(item)
      if item.source ~= "youtube" then return true end
      return item.hint ~= "shorts"
    end,
  },

  {
    kind = "only-shorts",
    label = "Only Shorts",
    blurb = "Keeps Shorts and holds everything else from YouTube.",
    keep = function(item)
      if item.source ~= "youtube" then return true end
      return item.hint == "shorts"
    end,
  },

  {
    kind = "watched-enough",
    label = "Watched enough",
    blurb = "Holds videos below a view count.",
    fields = {
      { name = "views", label = "At least this many views",
        type = "number", default = "1000" },
    },
    keep = function(item, settings)
      if item.source ~= "youtube" then return true end
      -- No count recorded is not a count of nothing: the details are
      -- fetched after discovery and a channel may hide them entirely.
      if item.views == nil or item.views == 0 then return true end
      return item.views >= (tonumber(settings.views) or 1000)
    end,
  },

  {
    kind = "well-liked",
    label = "Well liked",
    blurb = "Holds videos below a like count.",
    fields = {
      { name = "likes", label = "At least this many likes",
        type = "number", default = "100" },
    },
    keep = function(item, settings)
      if item.source ~= "youtube" then return true end
      if item.likes == nil or item.likes == 0 then return true end
      return item.likes >= (tonumber(settings.likes) or 100)
    end,
  },
}
