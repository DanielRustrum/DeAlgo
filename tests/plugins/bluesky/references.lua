-- What a typed or pasted reference means, for a Bluesky account, and where
-- its feed is.
--
-- Every account publishes an Atom feed at /profile/<handle>/rss. A handle is
-- a domain name, which is what tells one apart from a YouTube handle: both
-- begin with @, and only this one has a dot in it.

local M = {}

local function account(handle)
  return {
    key = "@" .. handle,
    feed = "https://bsky.app/profile/" .. handle .. "/rss",
    title = "@" .. handle,
  }
end

-- Asked when the box is already a Bluesky box. A handle here is a handle:
-- the guessing in `recognise` below exists only because an account may be
-- any domain, and there is nothing left to guess once somebody has dragged
-- this box out and typed into it.
function M.accept(typed)
  local handle = string.match(typed, "^@?([A-Za-z0-9%-%.]+)$")
  if not handle or string.find(handle, "%.%.") then
    return nil
  end
  if not string.find(handle, "%.") then
    -- No dot: they meant the one on Bluesky's own domain.
    handle = handle .. ".bsky.social"
  end
  if string.sub(handle, 1, 1) == "." or string.sub(handle, -1) == "." then
    return nil
  end
  return account(handle)
end

function M.recognise(reference)
  local host, path = string.match(reference, "^https?://([^/]+)(/.*)$")
  if host and string.match(host, "bsky%.app$") then
    local handle = string.match(path, "^/profile/([^/]+)")
    if handle then
      return account(handle)
    end
    return nil
  end
  if host then
    return nil   -- somebody else's address
  end

  -- A bare handle. It has to look like a domain: "@a.b" at the least, so
  -- that a plain "@handle" is left for YouTube to claim.
  local typed = string.match(reference, "^@?([A-Za-z0-9%-%.]+)$")
  if not typed or not string.find(typed, "%.") or string.find(typed, "%.%.") then
    return nil
  end
  if string.sub(typed, 1, 1) == "." or string.sub(typed, -1) == "." then
    return nil
  end

  local found = account(typed)
  -- A handle on Bluesky's own domain is certain. Any other domain is only a
  -- guess: Bluesky lets an account be any domain it owns, so "example.com"
  -- might be one and might equally be a newsletter nobody has written a
  -- plugin for yet. Saying so lets a plugin that *is* certain about it
  -- answer first.
  found.guess = not string.match(typed, "%.bsky%.social$")
  return found
end

return M
