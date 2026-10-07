-- Community posts: reading a channel's Posts tab.
--
-- There is no Data API for these — not in v3, not behind any scope — so
-- the only way to read them is the page a browser gets, and the shape of
-- what is in it is YouTube's to change without notice. Which is exactly
-- why it is a file of its own: when it breaks, one file is wrong.
--
-- Everything here fails soft. Nothing found is nothing returned; a
-- channel whose posts cannot be read still has its videos collected.
--
-- Needs the `network` and `clock` permissions, which arrive as the `net`
-- and `clock` globals.

local M = {}

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

-- Every post on a channel's Posts tab, newest first, as the host's `posts`
-- hook wants them.
function M.read(channel_id)
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

return M
