-- Reddit communities.
--
-- A subreddit publishes an Atom feed at /r/<name>/.rss and asks that it not
-- be read more than about once a minute. The host handles the waiting; this
-- only has to say where the feed is.

local function subreddit(name)
  return {
    key = "r/" .. name,
    feed = "https://www.reddit.com/r/" .. name .. "/.rss",
    title = "r/" .. name,
  }
end

return {
  id = "reddit",
  name = "Reddit",
  version = "1.0.0",
  api = 1,

  sources = {
    {
      kind = "reddit",
      label = "Reddit",
      example = "r/python, or a subreddit URL",
      -- A Reddit post is not a YouTube video, so it can only fill a feed
      -- that lives inside De-Algo.
      playlistable = false,

      recognise = function(reference)
        -- Typed as a community: "r/name", or "/r/name", with or without a
        -- trailing slash.
        local name = string.match(reference, "^/?r/([A-Za-z0-9_]+)/?$")
        if name and #name >= 2 and #name <= 30 then
          return subreddit(name)
        end

        -- Or pasted from the address bar, in any of the forms Reddit uses.
        local host, path = string.match(reference, "^https?://([^/]+)(/.*)$")
        if host and string.match(host, "reddit%.com$") then
          local found = string.match(path, "^/r/([A-Za-z0-9_]+)")
          if found then
            return subreddit(found)
          end
        end
        return nil
      end,

      -- The feed links each post at its comments page, which is where a
      -- reader wants to end up. Nothing to rewrite.
      item_url = function(_, link)
        return link
      end,

      -- Somewhere else the same feed can be read, for when Reddit will not
      -- have us. Open RSS is a nonprofit that generates feeds for sites that
      -- do not. Offered only: leaning on a service nobody here runs is the
      -- reader's call, and the host never fills it in by itself.
      mirror = function(key)
        local name = string.match(key, "^r/(.+)$")
        if name then
          return "https://openrss.org/reddit.com/r/" .. name
        end
        return nil
      end,
    },
  },

  -- Boxes for the canvas. Each judges Reddit's own posts and lets everything
  -- else by: a box about the shape of a Reddit post has no opinion about a
  -- YouTube upload, and a filter with no opinion passes.
  nodes = {
    {
      kind = "self-posts",
      label = "Self posts",
      blurb = "Keeps posts that were written, and holds bare link shares.",
      fields = {
        { name = "least", label = "At least this many characters of writing",
          type = "number", default = "80" },
      },
      keep = function(item, settings)
        if item.source ~= "reddit" then return true end
        -- A link share carries the destination and little else; somebody
        -- who wrote something wrote more than a line.
        return #(item.words or "") >= (tonumber(settings.least) or 80)
      end,
    },

    {
      kind = "asks-a-question",
      label = "Asks a question",
      blurb = "Keeps posts asking something — the help and advice ones.",
      keep = function(item)
        if item.source ~= "reddit" then return true end
        local title = item.title or ""
        if string.find(title, "?", 1, true) then return true end
        -- Plenty of questions are asked without the mark. The openers are
        -- the giveaway, and they are cheap to look for.
        local lower = string.lower(title)
        for _, opener in ipairs({
          "^how ", "^why ", "^what ", "^which ", "^when ", "^where ", "^who ",
          "^is ", "^are ", "^can ", "^could ", "^should ", "^would ", "^does ",
          "^do ", "^did ", "^help", "^anyone", "^any one",
        }) do
          if string.match(lower, opener) then return true end
        end
        return false
      end,
    },
  },
}
