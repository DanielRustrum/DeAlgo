# Clock and Log

## clock — permission `clock`

```lua
local now = clock.now()   -- seconds since 1970, UTC, as a number
```

Useful for turning "5 days ago" into a date:

```lua
local published_at = clock.now() - 5 * 86400
```

## log — permission `log`

Writes to Pamphlets's own log (what `make logs` shows), prefixed with your plugin's `name`.

```lua
log.info("skipped 3 posts with no text")
log.warn("the page shape changed; no posts found")
```

Messages longer than 500 characters are cut. There is no `print`.

**Related:** [Permissions](Permissions.md) · [Testing and Debugging](Testing%20and%20Debugging.md)
