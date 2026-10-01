# Newsletters

Follow a newsletter by where it lives — `platformer.news`, not `platformer.news/feed`. De-Algo finds
its feed for you.

## Adding one

1. Drag **Newsletter** from the top of the palette.
2. Type its address: `platformer.news`, `https://www.platformer.news/archive` — any page on the site.
3. Save, then wire it and switch it on like any [source](Sources.md).

It works with Substack, Ghost, beehiiv, Buttondown, WordPress and most sites that publish a feed.

## How the feed is found

In order, stopping at the first that is really a feed:

1. **What the page declares.** Most sites name their feed in the page's head.
2. **The usual places** — `/feed`, `/rss`, `/feed.xml`, `/rss.xml`, `/atom.xml`, `/index.xml`.
3. **The other of `www` and the bare domain.** Some sites serve their page on one and their feed only
   on the other.

Each candidate is read and must parse as a feed. At most 10 addresses are tried.

## Rules

- The address must contain a dot. A bare word like `platformer` is refused.
- `www.example.com` and `example.com` are the same newsletter, so you cannot add it twice.
- If no feed is found, nothing is added. If you know the feed's address, use a **Feed address** box.

**Related:** [Sources](Sources.md) · [Troubleshooting](../Troubleshooting.md)
