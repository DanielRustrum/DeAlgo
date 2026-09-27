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
      noun = "Bluesky account",
      blurb = "One account. Its posts, as they are made.",
      label = "Bluesky",
      example = "@name.bsky.social, or a profile URL",
      playlistable = false,

      -- Asked when the box is already a Bluesky box. A handle here is a
      -- handle: the guessing in `recognise` below exists only because an
      -- account may be any domain, and there is nothing left to guess once
      -- somebody has dragged this box out and typed into it.
      accept = function(typed)
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
      end,

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

      -- Where the account itself lives.
      home = function(key)
        return "https://bsky.app/profile/" .. (string.gsub(key, "^@", ""))
      end,

      item_url = function(_, link)
        return link
      end,
    },
  },

  -- One box, which is what a plugin with a single thing to offer looks like
  -- in the palette: the row shows under Plugins with no fold of its own.
  augmentations = {
    {
      kind = "said-something",
      label = "Said something",
      blurb = "Holds bare link shares with nothing written around them.",
      fields = {
        { name = "least", label = "At least this many characters",
          type = "number", default = "24" },
      },
      keep = function(item, settings)
        if item.source ~= "bluesky" then return true end
        -- A post's own text is its title here. Strip the addresses out of it
        -- before measuring: a link share is long without saying anything.
        local said = string.gsub(item.title or "", "https?://%S+", "")
        said = string.gsub(said, "^%s+", "")
        said = string.gsub(said, "%s+$", "")
        return #said >= (tonumber(settings.least) or 24)
      end,
    },
  },
}
