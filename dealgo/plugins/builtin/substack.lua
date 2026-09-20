-- Substack newsletters.
--
-- Every publication serves its archive at /feed on its own subdomain, and a
-- great many are read by their host alone: "name.substack.com" is how people
-- write one down.

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

return {
  id = "substack",
  name = "Substack",
  version = "1.0.0",
  api = 1,

  sources = {
    {
      kind = "substack",
      label = "Substack",
      example = "name.substack.com",
      playlistable = false,

      recognise = function(reference)
        local host = string.match(reference, "^https?://([^/]+)")
        if not host then
          host = string.match(reference, "^([A-Za-z0-9%-%.]+)$")
        end
        if host and string.match(host, "%.substack%.com$") then
          return publication(string.lower(host))
        end
        return nil
      end,

      item_url = function(_, link)
        return link
      end,
    },
  },
}
