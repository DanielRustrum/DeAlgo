-- Reddit communities: the plugin's identity and its parts.
--
--   references.lua   what a typed or pasted reference means, and its mirror
--   source.lua       the source: its names and links
--   conditions.lua   the conditions it adds to the canvas

return {
  id = "reddit",
  name = "Reddit",
  version = "1.0.0",
  api = 1,

  sources = { require("source") },
  augmentations = require("conditions"),
}
