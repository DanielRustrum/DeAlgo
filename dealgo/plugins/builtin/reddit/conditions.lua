-- Conditions for the canvas. Each judges Reddit's own posts and lets
-- everything else by: a condition about the shape of a Reddit post has no
-- opinion about a YouTube upload, and a filter with no opinion passes.

return {
  {
    kind = "self-posts",
    label = "Self posts",
    blurb = "Keeps posts that were written, and holds bare link shares.",
    fields = {
      { name = "least", label = "At least this many characters of writing",
        type = "number", default = "80" },
    },
    keep = function(item, settings)
      if item.source ~= "reddit" then return true end
      -- A link share carries the destination and little else; somebody who
      -- wrote something wrote more than a line.
      return #(item.words or "") >= (tonumber(settings.least) or 80)
    end,
  },

  {
    kind = "asks-a-question",
    label = "Asks a question",
    blurb = "Keeps posts asking something — the help and advice ones.",
    keep = function(item)
      if item.source ~= "reddit" then return true end
      local title = item.title or ""
      if string.find(title, "?", 1, true) then return true end
      -- Plenty of questions are asked without the mark. The openers are the
      -- giveaway, and they are cheap to look for.
      local lower = string.lower(title)
      for _, opener in ipairs({
        "^how ", "^why ", "^what ", "^which ", "^when ", "^where ", "^who ",
        "^is ", "^are ", "^can ", "^could ", "^should ", "^would ", "^does ",
        "^do ", "^did ", "^help", "^anyone", "^any one",
      }) do
        if string.match(lower, opener) then return true end
      end
      return false
    end,
  },
}
