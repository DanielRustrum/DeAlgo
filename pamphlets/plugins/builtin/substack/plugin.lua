-- Substack newsletters: the plugin's identity and its parts.
--
--   references.lua   what a typed or pasted address means
--   source.lua       the source: its names and links
--   conditions.lua   the condition it adds to the canvas

return {
  id = "substack",
  name = "Substack",
  version = "1.0.0",
  api = 1,

  sources = { require("source") },
  augmentations = require("conditions"),
}
