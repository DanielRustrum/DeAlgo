-- The Reddit community as a source: what it is called and where things live.

local references = require("references")

return {
  kind = "reddit",
  label = "Reddit",
  example = "r/python, or a subreddit URL",
  noun = "Subreddit",
  blurb = "One community. Everything it posts.",
  -- A Reddit post is not a YouTube video, so it can only fill a feed that
  -- lives inside Pamphlets.
  playlistable = false,

  accept = references.accept,
  recognise = references.recognise,
  mirror = references.mirror,

  -- Where the community itself lives.
  home = function(key)
    return "https://www.reddit.com/" .. key .. "/"
  end,

  -- The feed links each post at its comments page, which is where a reader
  -- wants to end up. Nothing to rewrite.
  item_url = function(_, link)
    return link
  end,
}
