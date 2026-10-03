-- YouTube channels: the plugin's identity, what it may do, and its parts.
--
-- Each part is a file of its own, loaded with `require`:
--
--   references.lua   what a typed or pasted reference means
--   source.lua       the source: its kinds of content, its feed, its links
--   posts.lua        reading a channel's Posts tab
--   conditions.lua   the conditions it adds to the canvas
--   api.lua          talking to the YouTube Data API v3
--   channels.lua     finding a channel through the API
--   publisher.lua    writing back to YouTube playlists
--   settings.lua     what the admin and each account set it up with
--   connect.lua      how Google signs people in

return {
  id = "youtube",
  name = "YouTube",
  version = "1.0.0",
  api = 1,

  -- The one thing this plugin cannot do for itself. De-Algo holds the
  -- credential and attaches it; this says which request to make.
  permissions = {
    {
      name = "network",
      why = "To read a channel's Posts tab. Community posts have no feed "
         .. "and no API behind them, so the page a browser gets is the only "
         .. "place they exist. Nothing else is fetched.",
    },
    {
      name = "clock",
      why = "A community post is dated “5 days ago” and nothing else, so "
         .. "the time now is what turns that into a date.",
    },
    {
      name = "account",
      why = "To resolve @handles, read video lengths and counts, and fill "
         .. "the YouTube playlists you point feeds at. Reading a channel's "
         .. "uploads needs none of this and works without it.",
    },
  },

  settings = require("settings"),
  connect = require("connect"),
  sources = { require("source") },
  augmentations = require("conditions"),
  publisher = require("publisher"),
}
