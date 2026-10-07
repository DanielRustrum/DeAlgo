-- The Substack newsletter as a source: what it is called and where things live.

local references = require("references")

return {
  kind = "substack",
  noun = "Newsletter",
  blurb = "One Substack. Every piece as it goes out.",
  label = "Substack",
  example = "name.substack.com",
  playlistable = false,

  accept = references.accept,
  recognise = references.recognise,

  -- Where the newsletter itself lives. The key is its domain.
  home = function(key)
    return "https://" .. key
  end,

  item_url = function(_, link)
    return link
  end,
}
