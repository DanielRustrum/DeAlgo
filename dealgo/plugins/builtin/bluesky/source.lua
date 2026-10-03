-- The Bluesky account as a source: what it is called and where things live.

local references = require("references")

return {
  kind = "bluesky",
  noun = "Bluesky account",
  blurb = "One account. Its posts, as they are made.",
  label = "Bluesky",
  example = "@name.bsky.social, or a profile URL",
  -- Its boxes on the canvas, from the colours the app allows.
  colour = "sky",
  playlistable = false,

  accept = references.accept,
  recognise = references.recognise,

  -- Where the account itself lives.
  home = function(key)
    return "https://bsky.app/profile/" .. (string.gsub(key, "^@", ""))
  end,

  item_url = function(_, link)
    return link
  end,
}
