# Sources and Parsing

`pamphlets/sources/` turns what someone typed into a feed address, reads feeds, and respects hosts'
rate limits. It makes no decisions about accounts, feeds or routing.

## From a reference to a source

`channels.add_source(reference, within=kind)` (`services/channels/adding.py`):

```
sources.resolve(typed, within)            # sources/kinds/ — no network
  ├─ within = a plugin kind  → registry.accept(kind, typed)       (generous: "python" → r/python)
  ├─ within = "newsletter"   → Resolved(key=site, feed_url="")     needs_finding
  ├─ within = "rss"          → the address as typed
  ├─ no kind                 → registry.recognise(typed)           (certain answers beat guesses)
  └─ unclaimed URL           → RSS; anything else → UnknownSource
then
  needs_host     → host-side resolution (YouTube @handle → channel id needs the account)
  needs_finding  → newsletter.find(site)
  otherwise      → syndication.fetch(feed_url) once, to prove it is a feed
  → Channel row (channel_id = key, source_kind, source_url, feed_url)
```

`sources/kinds/` owns only the vocabulary (`Resolved`, `SourceKind`, `UnknownSource`) and the two host
kinds — **RSS** and **Newsletter** — that belong to no service. Every other kind is a plugin's.

## Reading a feed — `sources/syndication/`

1. `patience.hold(url)` — refuse before asking if the host told us to wait.
2. GET with an RSS/Atom `Accept` header; `patience.note(response)`; raise on HTTP error.
3. `parse()`:
   - Reject anything whose root is not `rss`, `feed` or `rdf` and has no `channel` — HTML pages
     are often well-formed XML, and many sites answer 200 to any path.
   - RSS 2.0/1.0 and Atom read into one `Item` shape: `guid`, `title`, `link`, `summary`,
     `published_at`, `thumbnail_url`, `images`.
   - Pictures come from media tags, enclosures, and `<img>` in the HTML body, filtered to image
     hosts and file types; addresses are stripped from the summary words.
   - Items sorted newest first.

Uses the standard library `xml.etree.ElementTree` (expat). External entities are not resolved.

## Newsletters — `newsletter.py`

A newsletter is known by its site, not its feed. `find(site)`:

1. Read the home page (up to 512 KiB, following redirects).
2. `candidates()`, best first, capped at 10:
   - feeds the page **declares** (`<link rel="alternate">` of RSS, Atom or JSON Feed type);
   - the usual paths: `/feed`, `/rss`, `/feed.xml`, `/rss.xml`, `/atom.xml`, `/index.xml`;
   - on the `www.` sibling host: `/feed`, `/rss`, `/feed.xml`.
3. The first candidate that **parses as a feed** wins. None → "does not publish a feed that could
   be found".

## Rate limits — `patience.py`

Per-host advice, in memory, keyed by hostname:

| Signal | Wait |
| --- | --- |
| `Retry-After` > 0 (seconds or HTTP date) | That long |
| `X-RateLimit-Remaining` ≤ 0 | `X-RateLimit-Reset`, else 60 s |
| Status 403, 429 or 503 with neither | 60 s |

- Read on **every** response, including successes: Reddit announces an empty budget on a 200.
- The longest wait wins; capped at one hour.
- `hold()` raises `RateLimited`, which the sync engine reports as waiting, not failing.
- Lost on restart, deliberately: a fresh process has spent nothing.

## Mirrors

A source may have a `mirror_url`. `_read_feed` tries it **only** when the source refused
(`RateLimited`, 403, 429, 503) — never on 404 — and reports the original refusal if the mirror fails
too. Plugins may suggest a mirror (`kinds.suggest_mirror`).

## Embedded JSON — `embedded.py`

For pages with no feed: `script_object(html, name)` finds `name = {…}` in a page and parses the
balanced JSON; `find(value, key)` walks it depth-first and returns up to 500 matches. Exposed to
plugins as `net.embedded` and `net.find` (network permission).

## One item, any source — `items.py`

`Entry` (id, title, published, thumbnail, `hint`, `kind`, link, summary, images) and `Batch`.
The sync engine builds them from `syndication.Item` plus the plugin's `refine` answer.

**Related:** [Plugin Registry](Plugin%20Registry.md) · [The Sync Engine](The%20Sync%20Engine.md)
