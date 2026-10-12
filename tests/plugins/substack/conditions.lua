-- The condition this plugin adds to the canvas. It judges Substack's own
-- pieces and lets everything else by.

return {
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
}
