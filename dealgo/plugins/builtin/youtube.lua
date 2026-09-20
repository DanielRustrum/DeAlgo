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
    },
  },
}
