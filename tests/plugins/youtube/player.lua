-- The YouTube player, declared: the frame its videos play in, and the
-- messages YouTube's embed understands — its "widget" protocol, the one its
-- own IFrame API speaks — so the host can drive it without loading any of
-- YouTube's script into Pamphlets's page.

local function said(text) return text end

-- A command to the embed, as its IFrame API would send it.
local function command(name, argument)
  local args = argument and ('["' .. argument .. '"]') or "[]"
  return said('{"event":"command","func":"' .. name .. '","args":' .. args .. ',"id":1,"channel":"widget"}')
end

-- Each state, said either way the embed says it: as an event it was asked
-- to report, or inside the info it delivers.
local function state(number)
  return { { event = "onStateChange", info = number }, { ["info.playerState"] = number } }
end

return {
  -- Privacy-enhanced: no cookie is set until play is pressed.
  frame = "https://www.youtube-nocookie.com/embed/{key}?enablejsapi=1&rel=0&autoplay={autoplay}&origin={origin}",
  hello = {
    said('{"event":"listening","id":1,"channel":"widget"}'),
    command("addEventListener", "onStateChange"),
    command("addEventListener", "onError"),
  },
  say = { play = command("playVideo"), pause = command("pauseVideo"), stop = command("stopVideo") },
  hears = {
    ready = { event = "onReady" },
    playing = state(1),
    paused = state(2),
    ended = state(0),
    failed = { event = "onError" },
    time = "info.currentTime",
    duration = "info.duration",
  },
  -- The addresses that are one video, by its eleven-character id.
  videos = function(address)
    local id = address:match("^https?://youtu%.be/([%w_-]+)")
      or address:match("^https?://[%w%.]*youtube%.com/watch%?.-v=([%w_-]+)")
      or address:match("^https?://[%w%.]*youtube%.com/shorts/([%w_-]+)")
      or address:match("^https?://[%w%.]*youtube%.com/live/([%w_-]+)")
      or address:match("^https?://[%w%.]*youtube%.com/embed/([%w_-]+)")
      or address:match("^https?://[%w%.]*youtube%-nocookie%.com/embed/([%w_-]+)")
    if id and #id == 11 then return id end
    return nil
  end,
}
