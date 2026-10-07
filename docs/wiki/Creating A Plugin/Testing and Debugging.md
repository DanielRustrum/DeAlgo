# Testing and Debugging

## It will not load

Its row on **Admin → Plugins** says why, usually with a line number. See
[Plugin Files](Plugin%20Files.md#when-it-does-not-load).

## It loads but does nothing

- **Read the log** (`make logs`). Errors inside hooks are logged, e.g.
  *Hacker News could not judge an item: 12: attempt to index a nil value*, and the hook is treated as
  having no opinion — so a broken condition lets everything through.
- **Ask for `log`** and write your own lines: `log.info("saw " .. item.title)`.
- **Check the grants.** A permission the admin did not tick is simply absent. `if net then … end`.
- **Check `pamphlets` is answering.** It only answers inside `keep`, `rank`, `posts` and publisher
  functions — see [The pamphlets Object](The%20pamphlets%20Object.md#whose-account).
- **Press Test** on a trigger. Items your condition held show *held by <its label>*.

## Developing locally

Run Pamphlets from a checkout with `make dev` and put your plugin in `./data/plugins/<id>/plugin.lua`.
Restart to pick up changes, or re-upload it on the Plugins page.

## Testing from Python

The registry can load a folder of plugins and call them directly — no web app needed:

```python
from pathlib import Path
# Set PAMPHLETS_DATA_DIR to a scratch folder and PAMPHLETS_DATABASE_URL=sqlite:// first.
from pamphlets import outgoing
from pamphlets.plugins import registry
from pamphlets.plugins.capabilities import acting_for

found = registry.read(
    Path("my-plugins"),                                   # holds hackernews/plugin.lua
    granted={"hackernews": frozenset({"network", "log"})},  # what the admin would tick
    http=outgoing.client,
)
assert found.broken == [], [p.trouble for p in found.broken]

print(found.recognise("hn"))                       # what a typed reference becomes
print(found.refine("hackernews", {"guid": "1", "title": "t", "link": "", "summary": ""}))  # what refine adds

item = {"source": "hackernews", "title": "Ask HN: why?", "kind": "link"}
assert found.keeps("hackernews:no-ask-hn", item, {}) is False
print(found.ranks("<id>:<ordering kind>", item, {}))  # an ordering: a number

with acting_for(None):                        # so `pamphlets` and `account` answer
    print(found.keeps("hackernews:no-ask-hn", item, {}))
```

Pamphlets's own tests for the shipped plugins (`tests/test_plugin_nodes.py`, `tests/test_plugins.py`)
use exactly this.

**Related:** [The Sandbox](The%20Sandbox.md) · [Clock and Log](Clock%20and%20Log.md)
