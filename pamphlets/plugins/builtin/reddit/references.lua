-- What a typed or pasted reference means, for a Reddit community, and where
-- its feed is.
--
-- A subreddit publishes an Atom feed at /r/<name>/.rss and asks that it not
-- be read more than about once a minute. The host handles the waiting; this
-- only has to say where the feed is.

local M = {}

local function subreddit(name)
  return {
    key = "r/" .. name,
    feed = "https://www.reddit.com/r/" .. name .. "/.rss",
    title = "r/" .. name,
  }
end

-- Asked when the box is already a Subreddit box, so a bare name is a
-- subreddit rather than a guess about one. Nobody drags this out and types
-- the name of a newsletter.
function M.accept(typed)
  local name = string.match(typed, "^([A-Za-z0-9_]+)$")
  if name and #name >= 2 and #name <= 30 then
    return subreddit(name)
  end
  return nil
end

function M.recognise(reference)
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
end

-- Somewhere else the same feed can be read, for when Reddit will not have
-- us. Open RSS is a nonprofit that generates feeds for sites that do not.
-- Offered only: leaning on a service nobody here runs is the reader's call,
-- and the host never fills it in by itself.
function M.mirror(key)
  local name = string.match(key, "^r/(.+)$")
  if name then
    return "https://openrss.org/reddit.com/r/" .. name
  end
  return nil
end

return M
