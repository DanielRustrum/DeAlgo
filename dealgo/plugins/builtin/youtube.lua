-- YouTube channels.
--
-- The one source that can be written back to: a YouTube video may go into a
-- real YouTube playlist, and nothing else may. That is what `playlistable`
-- says, and the host refuses the wiring that would break it.
--
-- Reading a channel costs nothing and needs nobody's permission: every
-- channel publishes an Atom feed keyed by its UC… id. Turning an @handle
-- into that id is the exception — it needs the account's Google connection,
-- which is not a plugin's to hold. So a handle is recognised here and handed
-- back with `needs_host`, and the host finishes it.

local FEED = "https://www.youtube.com/feeds/videos.xml?channel_id="

local function by_id(id)
  return { key = id, feed = FEED .. id, title = id }
end

-- Asking the host to resolve it, because we know what it is and cannot
-- finish. The key is what was typed; the host replaces it with the real id.
local function ask_host(typed)
  return { key = typed, feed = "", title = typed, needs_host = true }
end

local HOSTS = {
  ["youtube.com"] = true, ["www.youtube.com"] = true,
  ["m.youtube.com"] = true, ["youtu.be"] = true,
}

return {
  id = "youtube",
  name = "YouTube",
  version = "1.0.0",
  api = 1,

  sources = {
    {
      kind = "youtube",
      label = "YouTube",
      example = "@handle, a channel URL, or a UC… id",
      playlistable = true,

      recognise = function(reference)
        -- A channel id, which needs no credentials at all.
        if string.match(reference, "^UC[%w_%-]+$") and #reference == 24 then
          return by_id(reference)
        end

        local host, path = string.match(reference, "^https?://([^/?#]+)([^?#]*)")
        if host then
          if not HOSTS[string.lower(host)] then
            return nil
          end
          local id = string.match(path or "", "^/channel/(UC[%w_%-]+)")
          if id and #id == 24 then
            return by_id(id)
          end
          -- /@handle, /c/name, /user/name: all need the API to resolve.
          return ask_host(reference)
        end

        -- A bare @handle with no dot in it. A dotted one is a domain, and
        -- belongs to whoever claims domains.
        local handle = string.match(reference, "^@([%w_%-%.]+)$")
        if handle and not string.find(handle, "%.") then
          return ask_host(reference)
        end
        return nil
      end,

      -- A video is addressed by its id rather than by a link, so the feed's
      -- own link is what the host already built. Nothing to change.
      item_url = function(_, link)
        return link
      end,

      -- What is YouTube's about a YouTube feed.
      --
      -- The feed is Atom and De-Algo reads Atom already, so there is no
      -- second parser here — rewriting a namespace-aware XML reader as Lua
      -- string matching would be a worse parser, not a plugin. What is left
      -- is the part only YouTube knows: that an entry's id carries the video
      -- id, and that a Short is told apart by the address it links to and by
      -- nothing else without spending API quota.
      refine = function(item)
        local video = string.match(item.guid or "", "^yt:video:([%w_%-]+)$")
        local link = item.link or ""
        return {
          -- A video is filed under its own id, not under the feed's guid.
          id = video,
          kind = "video",
          is_short = string.find(link, "/shorts/", 1, true) ~= nil,
        }
      end,
    },
  },

  -- Boxes for the canvas. Each judges YouTube's own items and lets everything
  -- else by untouched: a box asking about view counts must not swallow a
  -- subreddit that has none, and "no likes recorded" is not "nobody liked it".
  nodes = {
    {
      kind = "no-shorts",
      label = "No Shorts",
      blurb = "Holds Shorts on this path only.",
      keep = function(item)
        if item.source ~= "youtube" then return true end
        return not item.is_short
      end,
    },

    {
      kind = "only-shorts",
      label = "Only Shorts",
      blurb = "Keeps Shorts and holds everything else from YouTube.",
      keep = function(item)
        if item.source ~= "youtube" then return true end
        return item.is_short == true
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
  },
}
