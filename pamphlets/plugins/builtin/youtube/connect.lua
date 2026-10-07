-- How Google signs people in. Pamphlets does the sign-in and keeps the
-- token; `account.send` attaches it to requests for these hosts only.

return {
  name = "Google",
  authorize = "https://accounts.google.com/o/oauth2/v2/auth",
  token = "https://oauth2.googleapis.com/token",
  revoke = "https://oauth2.googleapis.com/revoke",
  -- Full YouTube scope: adding to and removing from a playlist need it.
  scopes = { "https://www.googleapis.com/auth/youtube" },
  -- A refresh token every time, even on a second sign-in.
  params = { access_type = "offline", prompt = "consent", include_granted_scopes = "true" },
  hosts = { "googleapis.com" },
  client_id = "client_id",
  client_secret = "client_secret",
  api_key = "api_key",
  -- Google resets the Data API quota at midnight Pacific, whatever the
  -- server's time zone.
  allowance = {
    daily = "daily_quota", reserve = "quota_reserve",
    timezone = "America/Los_Angeles", unit = "units", exhausted = "quotaExceeded",
  },
  -- Google says why it refused in error.errors[1].reason.
  refusal = function(answer)
    local errors = type(answer.error) == "table" and answer.error.errors
    local first = type(errors) == "table" and errors[1]
    return type(first) == "table" and first.reason or nil
  end,
  -- What Pamphlets shows as a toast while this account cannot write to YouTube yet.
  notices = {
    connect = "Connect your Google account so Pamphlets can add items to a YouTube "
           .. "playlist on your behalf.",
    reconnect = "Google needs you to sign in again. Items are still being queued, but "
             .. "nothing can reach the playlist until the account is reconnected.",
    setup = "Pamphlets can already watch channels, but writing to a YouTube playlist "
         .. "needs an OAuth client, which the admin sets on this plugin's card.",
  },
  about = "Reading a channel uses its public feed and costs nothing, so a short poll "
       .. "interval is fine. Only playlist writes are expensive: each added video costs "
       .. "50 of the default 10,000 daily units — about 200 videos a day, shared by "
       .. "everyone on this Pamphlets.",
}
