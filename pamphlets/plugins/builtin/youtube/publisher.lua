-- Writing back: YouTube playlists as Pamphlets's feeds.
--
-- Everything here is the YouTube Data API v3 and nothing else: which
-- endpoint answers what, which fields the answer carries, and what each call
-- costs. Pamphlets held all of this once and had no business knowing any of it.
--
-- Nothing here holds a credential. `account.send` says what request to make;
-- the host attaches the token, charges the allowance, and refuses to sign
-- anything addressed outside Google.

local api = require("api")
local channels = require("channels")

return {
  -- Published quota costs, in units. The daily budget is ten thousand, so
  -- the writes are what actually run it down — and a channel search is
  -- dearer than a hundred reads, which is why it is a last resort.
  costs = { read = 1, add = 50, remove = 50, create = 50, rename = 50, search = 100 },

  -- Where a playlist is opened, for the "Open on YouTube" link on a feed.
  address = function(playlist_id)
    return "https://www.youtube.com/playlist?list=" .. playlist_id
  end,

  resolve = function(reference)
    local found = channels.by_reference(reference)
    return found and { found } or {}
  end,

  describe = function(ids)
    local out = {}
    -- Fifty ids still cost a single unit, so they go in batches rather than
    -- one at a time.
    for _, batch in ipairs(api.batched(ids, 50)) do
      local page = api.get("channels", { part = "snippet", id = batch })
      for _, item in ipairs(api.items(page)) do
        out[#out + 1] = api.as_channel(item)
      end
    end
    return out
  end,

  details = function(ids)
    local out = {}
    for _, batch in ipairs(api.batched(ids, 50)) do
      -- Statistics come along for nothing at this price, which is what lets
      -- a sort box order by views or likes.
      local page = api.get("videos", {
        part = "contentDetails,snippet,status,statistics", id = batch,
      })
      for _, item in ipairs(api.items(page)) do
        local snippet = item.snippet or {}
        local counts = item.statistics or {}
        out[#out + 1] = {
          id = item.id,
          title = snippet.title or "",
          duration = api.seconds((item.contentDetails or {}).duration),
          live = snippet.liveBroadcastContent or "none",
          privacy = (item.status or {}).privacyStatus,
          views = api.count(counts.viewCount),
          likes = api.count(counts.likeCount),
        }
      end
    end
    return out
  end,

  playlists = function()
    local out = {}
    for _, item in ipairs(api.all("playlists", {
      part = "snippet,contentDetails,status", mine = "true", maxResults = 50,
    })) do
      out[#out + 1] = api.as_playlist(item)
    end
    return out
  end,

  playlist = function(id)
    local page = api.get("playlists", { part = "snippet,contentDetails,status", id = id })
    local first = api.items(page)[1]
    return first and { api.as_playlist(first) } or {}
  end,

  create = function(title, description, privacy)
    local made = account.send("POST",
      api.url("playlists", { part = "snippet,status" }),
      {
        snippet = { title = title, description = description or "" },
        status = { privacyStatus = privacy or "private" },
      }, 50)
    if not made or not made.id then return {} end
    return { {
      id = made.id,
      title = (made.snippet or {}).title or title,
      count = 0,
      privacy = (made.status or {}).privacyStatus,
    } }
  end,

  rename = function(id, title)
    -- The update has to carry the description as well: YouTube clears any
    -- mutable property a request leaves out, so renaming alone would wipe it.
    local page = api.get("playlists", { part = "snippet", id = id })
    local first = api.items(page)[1]
    if not first then return false end
    local said = account.send("PUT", api.url("playlists", { part = "snippet" }), {
      id = id,
      snippet = { title = title, description = (first.snippet or {}).description or "" },
    }, 50)
    return said ~= nil
  end,

  contents = function(id)
    local out = {}
    for _, item in ipairs(api.all("playlistItems", {
      part = "snippet", playlistId = id, maxResults = 50,
    })) do
      local snippet = item.snippet or {}
      local resource = snippet.resourceId or {}
      -- A playlist can hold things that are not videos. They are not ours
      -- to reason about, so they are not reported.
      if resource.kind == "youtube#video" then
        out[#out + 1] = {
          item_id = item.id,
          video_id = resource.videoId or "",
          position = snippet.position or 0,
          title = snippet.title or "",
        }
      end
    end
    return out
  end,

  add = function(playlist_id, video_id)
    local made = account.send("POST", api.url("playlistItems", { part = "snippet" }), {
      snippet = {
        playlistId = playlist_id,
        resourceId = { kind = "youtube#video", videoId = video_id },
      },
    }, 50)
    if not made or not made.id then return {} end
    return { { item_id = made.id } }
  end,

  remove = function(item_id)
    return account.send("DELETE", api.url("playlistItems", { id = item_id }), nil, 50) ~= nil
  end,
}
