-- Bluesky accounts.
--
-- Every account publishes an Atom feed at /profile/<handle>/rss. A handle is
-- a domain name, which is what tells one apart from a YouTube handle: both
-- begin with @, and only this one has a dot in it.

local function account(handle)
  return {
    key = "@" .. handle,
    feed = "https://bsky.app/profile/" .. handle .. "/rss",
    title = "@" .. handle,
  }
end

return {
  id = "bluesky",
  name = "Bluesky",
  version = "1.0.0",
  api = 1,

  sources = {
    {
      kind = "bluesky",
      label = "Bluesky",
      example = "@name.bsky.social, or a profile URL",
      playlistable = false,

      recognise = function(reference)
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

        -- A bare handle. It has to look like a domain: "@a.b" at the least,
        -- so that a plain "@handle" is left for YouTube to claim.
        local typed = string.match(reference, "^@?([A-Za-z0-9%-%.]+)$")
        if not typed or not string.find(typed, "%.") or string.find(typed, "%.%.") then
          return nil
        end
        if string.sub(typed, 1, 1) == "." or string.sub(typed, -1) == "." then
          return nil
        end

        local found = account(typed)
        -- A handle on Bluesky's own domain is certain. Any other domain is
        -- only a guess: Bluesky lets an account be any domain it owns, so
        -- "example.com" might be one and might equally be a newsletter
        -- nobody has written a plugin for yet. Saying so lets a plugin that
        -- *is* certain about it answer first.
        found.guess = not string.match(typed, "%.bsky%.social$")
        return found
      end,

      item_url = function(_, link)
        return link
      end,
    },
  },
}
