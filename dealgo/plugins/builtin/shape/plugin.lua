-- Augmentations that judge an item by its shape rather than by its words.
--
-- Several of them, so this plugin gets a dropdown of its own in the palette —
-- and so there is something to write an augmentation against without reaching
-- for a source at all. A plugin need not offer a source kind; these offer
-- none.
--
-- An augmentation is slotted under one of the app's own boxes and changes
-- what that box does. Which box it goes under says what it has to answer:
--
--   under = "filter"  →  keep(item, settings) returns true or false
--   under = "sort"    →  rank(item, settings) returns a number, biggest first
--
-- "filter" is the default, so the three conditions below say nothing about
-- it and the ordering at the end says so out loud.
--
-- Both are pure questions about one item. Nothing else is possible from in
-- here, which is the point — no network, no database, no way to reach
-- anything but the item in front of it.

local function number(settings, name, fallback)
  local given = tonumber(settings[name])
  if given == nil then return fallback end
  return given
end

return {
  id = "shape",
  name = "Shape",
  version = "1.0.0",
  api = 1,

  augmentations = {
    {
      kind = "long-enough",
      label = "Long enough",
      blurb = "Holds anything shorter than a length you set.",
      fields = {
        { name = "minutes", label = "At least this many minutes",
          type = "number", default = "5" },
      },
      keep = function(item, settings)
        -- Something with no duration is not short, it is unmeasured. A feed
        -- entry and a community post both have none, and holding those back
        -- for failing a length test nobody applied to them would be wrong.
        if item.duration == nil or item.duration == 0 then return true end
        return item.duration >= number(settings, "minutes", 5) * 60
      end,
    },

    {
      kind = "has-words",
      label = "Has words",
      blurb = "Holds anything whose title and body are shorter than you want.",
      fields = {
        { name = "least", label = "At least this many characters",
          type = "number", default = "40" },
      },
      keep = function(item, settings)
        local words = (item.title or "") .. " " .. (item.words or "")
        return #words >= number(settings, "least", 40)
      end,
    },

    {
      kind = "not-shouting",
      label = "Not shouting",
      blurb = "Holds titles that are mostly capitals.",
      fields = {
        { name = "most", label = "At most this share of capitals, per cent",
          type = "number", default = "60" },
      },
      keep = function(item, settings)
        local title = item.title or ""
        local letters, capitals = 0, 0
        for character in string.gmatch(title, "%a") do
          letters = letters + 1
          if string.match(character, "%u") then capitals = capitals + 1 end
        end
        -- A title of three letters is not shouting, it is short.
        if letters < 8 then return true end
        return (capitals / letters) * 100 <= number(settings, "most", 60)
      end,
    },

    -- An ordering rather than a condition, and the reason a plugin gets to
    -- write one: the app sorts by how long a video runs for, which is no
    -- length at all for something written. This measures what there is to
    -- read, so a feed of posts can be put longest-first.
    {
      kind = "by-length",
      label = "How much there is to read",
      blurb = "Orders by how much was written, not how long it runs for.",
      under = "sort",
      rank = function(item)
        return #(item.words or "") + #(item.title or "")
      end,
    },
  },
}
