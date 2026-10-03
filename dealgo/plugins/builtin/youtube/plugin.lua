-- YouTube channels.
--
-- The one source that can be written back to: a YouTube video may go into a
-- real YouTube playlist, and nothing else may. That is what `playlistable`
-- says, and the host refuses the wiring that would break it.
--
-- Reading a channel costs nothing and needs nobody's permission: every
-- channel publishes an Atom feed keyed by its UC… id. Turning an @handle
-- into that id is the exception — it needs the account's Google connection,
-- which is not a plugin's to hold. So a handle is recognised here and handed
-- back with `needs_host`, and the host finishes it.

local FEED = "https://www.youtube.com/feeds/videos.xml?channel_id="

local function by_id(id)
  return { key = id, feed = FEED .. id, title = id }
end

-- Asking the host to resolve it, because we know what it is and cannot
-- finish. The key is what was typed; the host replaces it with the real id.
local function ask_host(typed)
  return { key = typed, feed = "", title = typed, needs_host = true }
end

local HOSTS = {
  ["youtube.com"] = true, ["www.youtube.com"] = true,
  ["m.youtube.com"] = true, ["youtu.be"] = true,
}

-- ======================================================================
-- Talking to the YouTube Data API v3.
--
-- Nothing below holds a credential. `account.send` says what request to
-- make and the host attaches the token, so the worst a mistake in here
-- can do is ask Google the wrong question.
-- ======================================================================

-- ======================================================================
-- Community posts.
--
-- There is no Data API for these — not in v3, not behind any scope — so
-- the only way to read them is the page a browser gets, and the shape of
-- what is in it is YouTube's to change without notice. Which is exactly
-- why it belongs here: when it breaks, one file is wrong.
--
-- Everything below fails soft. Nothing found is nothing returned; a
-- channel whose posts cannot be read still has its videos collected.
-- ======================================================================

local POSTS = "https://www.youtube.com/channel/%s/posts"

-- Without a browser-shaped user agent YouTube serves a consent wall or
-- the no-JavaScript page, and neither carries the data.
local BROWSING = {
  ["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                .. "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  ["Accept-Language"] = "en-US,en;q=0.9",
}

local AGO = {
  second = 1, minute = 60, hour = 3600, day = 86400,
  week = 604800, month = 2592000, year = 31536000,  -- a month of 30 days
}

-- Flatten one of YouTube's run lists. A link carries its address as the
-- text only when it was short enough to show, so the runs are what a
-- reader actually sees.
local function runs_of(node)
  if type(node) ~= "table" then return "" end
  if node.simpleText then return tostring(node.simpleText) end
  local parts = {}
  for _, run in ipairs(node.runs or {}) do
    parts[#parts + 1] = tostring(run.text or "")
  end
  return table.concat(parts)
end

-- "5 days ago" is the only date a post carries, so the timestamp is
-- derived and approximate by construction. It has to be good enough to
-- sort a feed; posts arrive newest first, which settles anything closer.
local function posted_at(node)
  local said = runs_of(node)
  local count, unit = string.match(said, "(%d+)%s+(%a+)")
  if not count then return nil end
  local seconds = AGO[string.gsub(unit, "s$", "")]
  if not seconds then return nil end
  return clock.now() - (tonumber(count) * seconds)
end

local function widest(thumbnails)
  local best, widest_yet = nil, -1
  for _, thumb in ipairs(thumbnails or {}) do
    local width = tonumber(thumb.width) or 0
    if thumb.url and width > widest_yet then
      best, widest_yet = thumb.url, width
    end
  end
  return best
end

local function pictures_in(attachment)
  local urls = {}
  for _, image in ipairs(net.find(attachment, "backstageImageRenderer") or {}) do
    local url = widest(((image.image or {}).thumbnails) or {})
    if url then urls[#urls + 1] = url end
  end
  if #urls == 0 then
    -- A post with one picture keeps its thumbnails a level higher.
    for _, thumbs in ipairs(net.find(attachment, "thumbnails") or {}) do
      local url = widest(thumbs)
      if url and (string.find(url, "ggpht", 1, true)
                  or string.find(url, "ytimg", 1, true)) then
        urls[#urls + 1] = url
        break
      end
    end
  end
  return urls
end

local function read_posts(channel_id)
  if not string.match(channel_id or "", "^UC[%w_%-]+$") then return {} end

  local page = net.get(string.format(POSTS, channel_id), BROWSING)
  if not page then return {} end

  local found, seen = {}, {}
  for _, post in ipairs(net.embedded(page, "ytInitialData", "backstagePostRenderer") or {}) do
    local id = post.postId
    if id and not seen[id] then
      seen[id] = true
      local attachment = post.backstageAttachment or {}

      -- A post sharing one of the channel's own videos is worth marking:
      -- the video itself usually arrives through the Atom feed as well.
      local shared = nil
      for _, video in ipairs(net.find(attachment, "videoRenderer") or {}) do
        shared = video.videoId
        break
      end

      found[#found + 1] = {
        id = tostring(id),
        text = runs_of(post.contentText),
        published_at = posted_at(post.publishedTimeText),
        images = pictures_in(attachment),
        shared_video = shared,
      }
    end
  end
  return found
end

local API = "https://www.googleapis.com/youtube/v3/"

-- Percent-encoding, because a channel title searched for can hold
-- anything and a query is not a place to put it raw.
local function escaped(value)
  return (string.gsub(tostring(value), "[^%w%-%_%.%~]", function(ch)
    return string.format("%%%02X", string.byte(ch))
  end))
end

local function yt_url(path, params)
  local parts = {}
  for name, value in pairs(params or {}) do
    parts[#parts + 1] = escaped(name) .. "=" .. escaped(value)
  end
  table.sort(parts)  -- so the same question is the same address every time
  if #parts == 0 then return API .. path end
  return API .. path .. "?" .. table.concat(parts, "&")
end

-- The published price list, by the endpoint being asked. Every read is a
-- single unit however much it brings back; a search is a hundred, which
-- is why it is never the first thing tried.
local function yt_get(path, params)
  return account.send("GET", yt_url(path, params), nil, path == "search" and 100 or 1)
end

local function yt_items(page)
  if type(page) ~= "table" then return {} end
  return page.items or {}
end

-- Pages, up to a stop. A channel with more playlists than this has a
-- bigger problem than a missing page, and an unbounded loop against a
-- service that keeps answering is not something to leave in a sync.
local function yt_all(path, params)
  local out, token = {}, nil
  for _ = 1, 20 do
    local asking = {}
    for name, value in pairs(params) do asking[name] = value end
    if token then asking.pageToken = token end

    local page = yt_get(path, asking)
    for _, item in ipairs(yt_items(page)) do out[#out + 1] = item end

    token = type(page) == "table" and page.nextPageToken or nil
    if not token then break end
  end
  return out
end

-- Ids in groups, comma-joined the way the API takes them. Fifty at a
-- time costs one unit, and one at a time would cost fifty.
local function yt_batched(ids, size)
  local batches, current = {}, {}
  for _, id in ipairs(ids or {}) do
    current[#current + 1] = tostring(id)
    if #current == size then
      batches[#batches + 1] = table.concat(current, ",")
      current = {}
    end
  end
  if #current > 0 then batches[#batches + 1] = table.concat(current, ",") end
  return batches
end

-- ISO-8601 (`PT4M13S`) as seconds.
local function yt_seconds(raw)
  if type(raw) ~= "string" then return nil end
  local days = tonumber(string.match(raw, "P(%d+)D") or 0) or 0
  local rest = string.match(raw, "T(.*)$") or ""
  local hours = tonumber(string.match(rest, "(%d+)H") or 0) or 0
  local minutes = tonumber(string.match(rest, "(%d+)M") or 0) or 0
  local seconds = tonumber(string.match(rest, "(%d+)S") or 0) or 0
  return days * 86400 + hours * 3600 + minutes * 60 + seconds
end

-- Counts arrive as strings, and are simply absent where a channel has
-- hidden them. Absent is not zero, so it stays nothing.
local function yt_count(raw)
  if type(raw) ~= "string" or not string.match(raw, "^%d+$") then return nil end
  return tonumber(raw)
end

local function yt_as_channel(item)
  local snippet = item.snippet or {}
  local thumbs = snippet.thumbnails or {}
  local thumb = thumbs.medium or thumbs.default or {}
  return {
    id = item.id or "",
    title = snippet.title or "",
    handle = snippet.customUrl,
    thumbnail = thumb.url,
    description = snippet.description or "",
  }
end

local function yt_as_playlist(item)
  return {
    id = item.id,
    title = (item.snippet or {}).title or "",
    count = (item.contentDetails or {}).itemCount or 0,
    privacy = (item.status or {}).privacyStatus,
  }
end

local function yt_one_channel(params)
  return yt_items(yt_get("channels", params))[1]
end

-- What was typed, as one of: an id, an @handle, a legacy username, or
-- words to search for. The same shapes `recognise` knows, taken further
-- because here there is an account to ask with.
local function yt_classify(raw)
  local text = string.match(tostring(raw or ""), "^%s*(.-)%s*$")
  if text == "" then return nil end
  if string.match(text, "^UC[%w_%-]+$") and #text == 24 then return "id", text end
  if string.sub(text, 1, 1) == "@" then return "handle", text end

  if not string.find(text, "://", 1, true)
     and string.match(text, "^[%w%.]*youtube%.com/") then
    text = "https://" .. text
  end

  if string.find(text, "://", 1, true) then
    local path = string.match(text, "^https?://[^/?#]+([^?#]*)") or ""
    local id = string.match(path, "^/channel/([%w_%-]+)")
    if id then return "id", id end
    local user = string.match(path, "^/user/([^/]+)")
    if user then return "username", user end
    local handle = string.match(path, "^/(@[^/]+)")
    if handle then return "handle", handle end
    local named = string.match(path, "^/c/([^/]+)")
    if named then return "search", named end
    return nil
  end

  return "search", text
end

local function yt_channel_by_reference(reference)
  local kind, value = yt_classify(reference)
  if not kind then return nil end

  if kind == "id" then
    local found = yt_one_channel({ part = "snippet", id = value })
    return found and yt_as_channel(found) or nil
  end

  if kind == "handle" or kind == "username" then
    local asking = { part = "snippet" }
    if kind == "handle" then asking.forHandle = value else asking.forUsername = value end
    local found = yt_one_channel(asking)
    if found then return yt_as_channel(found) end
    -- Nothing under that name. Fall through to a search for the words in
    -- it, which is what a person typing a stale handle meant.
    value = string.gsub(value, "^@", "")
  end

  -- Last resort, at a hundred units a go.
  local hit = yt_items(yt_get("search", {
    part = "snippet", type = "channel", q = value, maxResults = 1,
  }))[1]
  if not hit then return nil end

  local id = (hit.snippet or {}).channelId or (hit.id or {}).channelId
  if not id then return nil end
  local found = yt_one_channel({ part = "snippet", id = id })
  return found and yt_as_channel(found) or nil
end

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

  sources = {
    {
      kind = "youtube",
      label = "YouTube",
      example = "@handle, a channel URL, or a UC… id",
      noun = "YouTube channel",
      blurb = "One channel. Uploads, and community posts if you want them.",
      -- Its boxes on the canvas, from the colours the app allows.
      colour = "red",
      playlistable = true,

      -- Asked when the box is already a YouTube box. A bare word here is
      -- a channel to go and look up, which `recognise` cannot assume of a
      -- reference nobody has placed yet — "python" is not YouTube's to
      -- claim until somebody says it is.
      accept = function(typed)
        local name = string.match(typed, "^[%w_%-%. ]+$")
        if name and not string.find(name, "^UC") then
          return ask_host(name)
        end
        return nil
      end,

      recognise = function(reference)
        -- A channel id, which needs no credentials at all.
        if string.match(reference, "^UC[%w_%-]+$") and #reference == 24 then
          return by_id(reference)
        end

        local host, path = string.match(reference, "^https?://([^/?#]+)([^?#]*)")
        if host then
          if not HOSTS[string.lower(host)] then
            return nil
          end
          local id = string.match(path or "", "^/channel/(UC[%w_%-]+)")
          if id and #id == 24 then
            return by_id(id)
          end
          -- /@handle, /c/name, /user/name: all need the API to resolve.
          return ask_host(reference)
        end

        -- A bare @handle with no dot in it. A dotted one is a domain, and
        -- belongs to whoever claims domains.
        local handle = string.match(reference, "^@([%w_%-%.]+)$")
        if handle and not string.find(handle, "%.") then
          return ask_host(reference)
        end
        return nil
      end,

      -- Where the channel itself lives, for a link out to it.
      home = function(channel_id)
        return "https://www.youtube.com/channel/" .. channel_id
      end,

      -- What the feed does not carry. Every other source here has one
      -- place its content lives; YouTube has two, and the second has no
      -- feed at all.
      posts = function(channel_id)
        return read_posts(channel_id)
      end,

      -- A video is addressed by its id rather than by a link, so the feed's
      -- own link is what the host already built. Nothing to change.
      item_url = function(_, link)
        return link
      end,

      -- What is YouTube's about a YouTube feed.
      --
      -- The feed is Atom and De-Algo reads Atom already, so there is no
      -- second parser here — rewriting a namespace-aware XML reader as Lua
      -- string matching would be a worse parser, not a plugin. What is left
      -- is the part only YouTube knows: that an entry's id carries the video
      -- id, and that a Short is told apart by the address it links to and by
      -- nothing else without spending API quota.
      refine = function(item)
        local video = string.match(item.guid or "", "^yt:video:([%w_%-]+)$")
        local link = item.link or ""
        return {
          -- A video is filed under its own id, not under the feed's guid.
          id = video,
          kind = "video",
          is_short = string.find(link, "/shorts/", 1, true) ~= nil,
        }
      end,
    },
  },

  -- Conditions for the canvas: augmentations that slot under a Filter box
  -- and narrow what comes past it. Each judges YouTube's own items and lets
  -- everything else by untouched — a condition asking about view counts must
  -- not swallow a subreddit that has none, and "no likes recorded" is not
  -- "nobody liked it".
  --
  -- What kind of thing a YouTube item is lives here rather than in the host:
  -- a Short, a premiere and a community post are YouTube's own distinctions,
  -- and the host has no business knowing the difference.
  augmentations = {
    {
      kind = "no-videos",
      label = "No videos",
      blurb = "Holds ordinary uploads.",
      keep = function(item)
        if item.source ~= "youtube" then return true end
        if item.kind ~= "video" then return true end
        -- A Short and a broadcast are their own things, each with a
        -- condition of its own. This one is about everything else.
        if item.is_short then return true end
        if item.live == "live" or item.live == "upcoming" then return true end
        return false
      end,
    },

    {
      kind = "no-live",
      label = "No live",
      blurb = "Holds broadcasts, live or still to come.",
      keep = function(item)
        if item.source ~= "youtube" then return true end
        return not (item.live == "live" or item.live == "upcoming")
      end,
    },

    {
      kind = "no-posts",
      label = "No posts",
      blurb = "Holds community posts.",
      keep = function(item)
        if item.source ~= "youtube" then return true end
        return item.kind ~= "post"
      end,
    },

    {
      kind = "no-shorts",
      label = "No Shorts",
      blurb = "Holds Shorts on this path only.",
      keep = function(item)
        if item.source ~= "youtube" then return true end
        return not item.is_short
      end,
    },

    {
      kind = "only-shorts",
      label = "Only Shorts",
      blurb = "Keeps Shorts and holds everything else from YouTube.",
      keep = function(item)
        if item.source ~= "youtube" then return true end
        return item.is_short == true
      end,
    },

    {
      kind = "watched-enough",
      label = "Watched enough",
      blurb = "Holds videos below a view count.",
      fields = {
        { name = "views", label = "At least this many views",
          type = "number", default = "1000" },
      },
      keep = function(item, settings)
        if item.source ~= "youtube" then return true end
        -- No count recorded is not a count of nothing: the details are
        -- fetched after discovery and a channel may hide them entirely.
        if item.views == nil or item.views == 0 then return true end
        return item.views >= (tonumber(settings.views) or 1000)
      end,
    },

    {
      kind = "well-liked",
      label = "Well liked",
      blurb = "Holds videos below a like count.",
      fields = {
        { name = "likes", label = "At least this many likes",
          type = "number", default = "100" },
      },
      keep = function(item, settings)
        if item.source ~= "youtube" then return true end
        if item.likes == nil or item.likes == 0 then return true end
        return item.likes >= (tonumber(settings.likes) or 100)
      end,
    },
  },

  -- ====================================================================
  -- Writing back.
  --
  -- Everything below is the YouTube Data API v3 and nothing else: which
  -- endpoint answers what, which fields the answer carries, and what each
  -- call costs. De-Algo held all of this once and had no business knowing
  -- any of it.
  --
  -- Nothing here holds a credential. `account.send` says what request to
  -- make; the host attaches the token, charges the allowance, and refuses
  -- to sign anything addressed outside Google.
  -- ====================================================================

  publisher = {
    -- Published quota costs, in units. The daily budget is ten thousand,
    -- so the writes are what actually run it down — and a channel search
    -- is dearer than a hundred reads, which is why it is a last resort.
    costs = { read = 1, add = 50, remove = 50, create = 50, rename = 50, search = 100 },

    resolve = function(reference)
      local found = yt_channel_by_reference(reference)
      return found and { found } or {}
    end,

    describe = function(ids)
      local out = {}
      -- Fifty ids still cost a single unit, so they go in batches rather
      -- than one at a time.
      for _, batch in ipairs(yt_batched(ids, 50)) do
        local page = yt_get("channels", { part = "snippet", id = batch })
        for _, item in ipairs(yt_items(page)) do
          out[#out + 1] = yt_as_channel(item)
        end
      end
      return out
    end,

    details = function(ids)
      local out = {}
      for _, batch in ipairs(yt_batched(ids, 50)) do
        -- Statistics come along for nothing at this price, which is what
        -- lets a sort box order by views or likes.
        local page = yt_get("videos", {
          part = "contentDetails,snippet,status,statistics", id = batch,
        })
        for _, item in ipairs(yt_items(page)) do
          local snippet = item.snippet or {}
          local counts = item.statistics or {}
          out[#out + 1] = {
            id = item.id,
            title = snippet.title or "",
            duration = yt_seconds((item.contentDetails or {}).duration),
            live = snippet.liveBroadcastContent or "none",
            privacy = (item.status or {}).privacyStatus,
            views = yt_count(counts.viewCount),
            likes = yt_count(counts.likeCount),
          }
        end
      end
      return out
    end,

    playlists = function()
      local out = {}
      for _, item in ipairs(yt_all("playlists", {
        part = "snippet,contentDetails,status", mine = "true", maxResults = 50,
      })) do
        out[#out + 1] = yt_as_playlist(item)
      end
      return out
    end,

    playlist = function(id)
      local page = yt_get("playlists", { part = "snippet,contentDetails,status", id = id })
      local first = yt_items(page)[1]
      return first and { yt_as_playlist(first) } or {}
    end,

    create = function(title, description, privacy)
      local made = account.send("POST",
        yt_url("playlists", { part = "snippet,status" }),
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
      -- The update has to carry the description as well: YouTube clears
      -- any mutable property a request leaves out, so renaming alone
      -- would wipe it.
      local page = yt_get("playlists", { part = "snippet", id = id })
      local first = yt_items(page)[1]
      if not first then return false end
      local said = account.send("PUT", yt_url("playlists", { part = "snippet" }), {
        id = id,
        snippet = { title = title, description = (first.snippet or {}).description or "" },
      }, 50)
      return said ~= nil
    end,

    contents = function(id)
      local out = {}
      for _, item in ipairs(yt_all("playlistItems", {
        part = "snippet", playlistId = id, maxResults = 50,
      })) do
        local snippet = item.snippet or {}
        local resource = snippet.resourceId or {}
        -- A playlist can hold things that are not videos. They are not
        -- ours to reason about, so they are not reported.
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
      local made = account.send("POST", yt_url("playlistItems", { part = "snippet" }), {
        snippet = {
          playlistId = playlist_id,
          resourceId = { kind = "youtube#video", videoId = video_id },
        },
      }, 50)
      if not made or not made.id then return {} end
      return { { item_id = made.id } }
    end,

    remove = function(item_id)
      return account.send("DELETE", yt_url("playlistItems", { id = item_id }), nil, 50) ~= nil
    end,
  },
}
