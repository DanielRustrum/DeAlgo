-- One condition, which is what a plugin with a single thing to offer looks
-- like in the palette: the row shows under Plugins with no fold of its own.

return {
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
}
