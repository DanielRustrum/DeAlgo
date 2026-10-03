-- Finding a channel from whatever was typed, by asking the Data API.
--
-- The same shapes `references` knows, taken further: here there is an
-- account to ask with, so a handle, a legacy username or a name can be
-- turned into a channel.

local api = require("api")

local M = {}

-- What was typed, as one of: an id, an @handle, a legacy username, or
-- words to search for.
local function classify(raw)
  local text = string.match(tostring(raw or ""), "^%s*(.-)%s*$")
  if text == "" then return nil end
  if string.match(text, "^UC[%w_%-]+$") and #text == 24 then return "id", text end
  if string.sub(text, 1, 1) == "@" then return "handle", text end

  if not string.find(text, "://", 1, true)
     and string.match(text, "^[%w%.]*youtube%.com/") then
    text = "https://" .. text
  end

  if string.find(text, "://", 1, true) then
    local path = string.match(text, "^https?://[^/?#]+([^?#]*)") or ""
    local id = string.match(path, "^/channel/([%w_%-]+)")
    if id then return "id", id end
    local user = string.match(path, "^/user/([^/]+)")
    if user then return "username", user end
    local handle = string.match(path, "^/(@[^/]+)")
    if handle then return "handle", handle end
    local named = string.match(path, "^/c/([^/]+)")
    if named then return "search", named end
    return nil
  end

  return "search", text
end

-- The channel a reference names, as a host channel row, or nil.
function M.by_reference(reference)
  local kind, value = classify(reference)
  if not kind then return nil end

  if kind == "id" then
    local found = api.one_channel({ part = "snippet", id = value })
    return found and api.as_channel(found) or nil
  end

  if kind == "handle" or kind == "username" then
    local asking = { part = "snippet" }
    if kind == "handle" then asking.forHandle = value else asking.forUsername = value end
    local found = api.one_channel(asking)
    if found then return api.as_channel(found) end
    -- Nothing under that name. Fall through to a search for the words in
    -- it, which is what a person typing a stale handle meant.
    value = string.gsub(value, "^@", "")
  end

  -- Last resort, at a hundred units a go.
  local hit = api.items(api.get("search", {
    part = "snippet", type = "channel", q = value, maxResults = 1,
  }))[1]
  if not hit then return nil end

  local id = (hit.snippet or {}).channelId or (hit.id or {}).channelId
  if not id then return nil end
  local found = api.one_channel({ part = "snippet", id = id })
  return found and api.as_channel(found) or nil
end

return M
