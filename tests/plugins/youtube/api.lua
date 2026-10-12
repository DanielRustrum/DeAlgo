-- Talking to the YouTube Data API v3: addresses, paging, batching, and
-- reading the answers into plain rows.
--
-- Nothing here holds a credential. `account.send` says what request to
-- make and the host attaches the token, so the worst a mistake in here
-- can do is ask Google the wrong question.

local M = {}

local API = "https://www.googleapis.com/youtube/v3/"

-- Percent-encoding, because a channel title searched for can hold
-- anything and a query is not a place to put it raw.
local function escaped(value)
  return (string.gsub(tostring(value), "[^%w%-%_%.%~]", function(ch)
    return string.format("%%%02X", string.byte(ch))
  end))
end

-- An endpoint's address with its query, the same for the same question.
function M.url(path, params)
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
function M.get(path, params)
  return account.send("GET", M.url(path, params), nil, path == "search" and 100 or 1)
end

-- The rows of one page of answers; none for no answer.
function M.items(page)
  if type(page) ~= "table" then return {} end
  return page.items or {}
end

-- Pages, up to a stop. A channel with more playlists than this has a
-- bigger problem than a missing page, and an unbounded loop against a
-- service that keeps answering is not something to leave in a sync.
function M.all(path, params)
  local out, token = {}, nil
  for _ = 1, 20 do
    local asking = {}
    for name, value in pairs(params) do asking[name] = value end
    if token then asking.pageToken = token end

    local page = M.get(path, asking)
    for _, item in ipairs(M.items(page)) do out[#out + 1] = item end

    token = type(page) == "table" and page.nextPageToken or nil
    if not token then break end
  end
  return out
end

-- Ids in groups, comma-joined the way the API takes them. Fifty at a
-- time costs one unit, and one at a time would cost fifty.
function M.batched(ids, size)
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
function M.seconds(raw)
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
function M.count(raw)
  if type(raw) ~= "string" or not string.match(raw, "^%d+$") then return nil end
  return tonumber(raw)
end

-- A channel resource as the host's channel row.
function M.as_channel(item)
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

-- A playlist resource as the host's playlist row.
function M.as_playlist(item)
  return {
    id = item.id,
    title = (item.snippet or {}).title or "",
    count = (item.contentDetails or {}).itemCount or 0,
    privacy = (item.status or {}).privacyStatus,
  }
end

-- The first channel a `channels` query finds, or nil.
function M.one_channel(params)
  return M.items(M.get("channels", params))[1]
end

return M
