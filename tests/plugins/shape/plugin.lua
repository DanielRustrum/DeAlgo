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
-- "filter" is the default, so the conditions say nothing about it and the
-- ordering says so out loud.
--
-- Both are pure questions about one item. Nothing else is possible from in
-- here, which is the point — no network, no database, no way to reach
-- anything but the item in front of it.
--
-- Its parts:
--
--   conditions.lua   the three conditions, in palette order
--   orderings.lua    the ordering
--   fields.lua       reading a condition's fields as numbers

-- Conditions first, then the ordering: the order the palette lists them in.
local augmentations = {}
for _, part in ipairs({ require("conditions"), require("orderings") }) do
  for _, one in ipairs(part) do
    augmentations[#augmentations + 1] = one
  end
end

return {
  id = "shape",
  name = "Shape",
  version = "1.0.0",
  api = 1,

  augmentations = augmentations,
}
