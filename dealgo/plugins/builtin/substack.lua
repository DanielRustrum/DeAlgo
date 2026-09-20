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

  nodes = {
    {
      kind = "long-read",
      label = "Long read",
      blurb = "Holds the short ones — notes, announcements, link round-ups.",
      fields = {
        { name = "least", label = "At least this many characters",
          type = "number", default = "1200" },
      },
      keep = function(item, settings)
        if item.source ~= "substack" then return true end
        -- A paywalled post arrives as a couple of paragraphs and a button,
        -- which this holds along with the genuinely short ones. Both are
        -- things somebody asking for long reads did not ask for.
        return #(item.words or "") >= (tonumber(settings.least) or 1200)
      end,
    },
  },
}
