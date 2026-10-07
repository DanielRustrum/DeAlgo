-- What a typed or pasted reference means, for a Substack newsletter, and
-- where its feed is.
--
-- Every publication serves its archive at /feed on its own subdomain, and a
-- great many are read by their host alone: "name.substack.com" is how people
-- write one down.

local M = {}

local function publication(host)
  local name = string.match(host, "^([^%.]+)")
  return {
    key = host,
    feed = "https://" .. host .. "/feed",
    -- "my-newsletter" reads better as "My Newsletter" until the feed itself
    -- says what it is called, which it does on the first poll.
    title = (string.gsub(name, "%-", " ")),
  }
end

-- Asked when the box is already a Newsletter box, so a bare name is the
-- newsletter of that name on Substack's own domain — which is how almost all
-- of them are addressed.
function M.accept(typed)
  local name = string.match(typed, "^([A-Za-z0-9%-]+)$")
  if name then
    return publication(string.lower(name) .. ".substack.com")
  end
  return nil
end

function M.recognise(reference)
  local host = string.match(reference, "^https?://([^/]+)")
  if not host then
    host = string.match(reference, "^([A-Za-z0-9%-%.]+)$")
  end
  if host and string.match(host, "%.substack%.com$") then
    return publication(string.lower(host))
  end
  return nil
end

return M
