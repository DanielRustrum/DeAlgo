-- What this plugin asks to be set up with.
--
-- `app`: once for the whole install, on this plugin's card under Admin →
-- Plugins — the Google project everyone signs in through, and what it may
-- spend. Each can also come from DEALGO_PLUGIN_YOUTUBE_<NAME>.
-- `user`: each account's own, in its YouTube block under Settings.

return {
  app = {
    {
      name = "client_id", label = "OAuth client id",
      placeholder = "…apps.googleusercontent.com",
      hint = "From an OAuth client of type “Web application” in the Google Cloud console, "
          .. "on a project with the YouTube Data API v3 enabled.",
    },
    { name = "client_secret", label = "OAuth client secret", type = "secret",
      placeholder = "GOCSPX-…" },
    {
      name = "api_key", label = "API key (optional)", type = "secret",
      hint = "Lets @handles be looked up before anyone has signed in.",
    },
    {
      name = "daily_quota", label = "Daily quota", type = "number", default = 10000,
      hint = "Units per day on the Google project. 10,000 is Google's default.",
    },
    {
      name = "quota_reserve", label = "Held back from syncing", type = "number", default = 0,
      hint = "Units syncing leaves for things done by hand late in the day.",
    },
  },
  user = {
    {
      name = "shorts_max_seconds", label = "Longest video counted as a Short",
      type = "number", default = 60,
      hint = "In seconds. A video linked as a Short is one whatever its length.",
    },
  },
}
