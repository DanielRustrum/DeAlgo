-- Orderings: under a Sort box, `rank(item, settings)` returns a number, and
-- the biggest comes first.

return {
  -- The reason a plugin gets to write one: the app sorts by how long a video
  -- runs for, which is no length at all for something written. This measures
  -- what there is to read, so a feed of posts can be put longest-first.
  {
    kind = "by-length",
    label = "How much there is to read",
    blurb = "Orders by how much was written, not how long it runs for.",
    under = "sort",
    rank = function(item)
      return #(item.words or "") + #(item.title or "")
    end,
  },
}
