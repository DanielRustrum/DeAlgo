-- What a typed or pasted reference means, for a YouTube channel.
--
-- Reading a channel costs nothing and needs nobody's permission: every
-- channel publishes an Atom feed keyed by its UC… id. Turning an @handle
-- into that id is the exception — it needs the account's sign-in, which is
-- not a plugin's to hold. So a handle is recognised here and handed back
-- with `needs_host`, and the host finishes it (through `publisher.resolve`).

local M = {}

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

-- Asked when the box is already a YouTube box. A bare word here is a
-- channel to go and look up, which `recognise` cannot assume of a reference
-- nobody has placed yet — "python" is not YouTube's to claim until somebody
-- says it is.
function M.accept(typed)
  local name = string.match(typed, "^[%w_%-%. ]+$")
  if name and not string.find(name, "^UC") then
    return ask_host(name)
  end
  return nil
end

function M.recognise(reference)
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
end

return M
