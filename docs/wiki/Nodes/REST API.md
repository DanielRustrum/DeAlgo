# REST API

A **REST API** source reads any JSON API: a service's own API, a search, a status page, your own
app. It gives **data**, not items: its one port is `{ }`, and its answer goes to operation boxes,
a [Transform](Transform.md) or a [Format](Format.md) box — to be counted, filtered, or drawn on a
pamphlet. It never fills a feed. Its whole answer is kept each time it is checked.

## Adding one

1. Drag **REST API** out of the palette's Sources, and type the API's address.
2. Open the box. Under **What to read**, check or set:
   - **API address**: where to read it from.
   - **List of items**: where in the answer the list is.
   - **Id, Title, Link, Date, Picture, Summary**: which field of each item holds each one.
   - **Header with its key**: for an API that needs one, such as `Authorization` with
     `Bearer …`, or `X-API-Key` with the key.
3. Press **Try it**. It reads the API with the fields as they stand, without saving, and shows
   the first few items as they'll arrive.
4. **Save**, then wire a trigger into it, and its `{ }` port to where its data goes.

An API that needs its key before it answers can still be added: set the key on the box afterwards.

## Paths

Each field is a path into the JSON, with dots between the steps and numbers for a place in a list:

| The answer | The path |
| --- | --- |
| `{"data": {"children": [ … ]}}` | `data.children` |
| `{"title": {"rendered": "…"}}` | `title.rendered`, or just `title` |
| `{"images": [{"url": "…"}]}` | `images.0.url` |

**Leave a field empty to have it guessed.** The list is looked for under the usual names (`items`,
`results`, `data`, `entries`, `hits` and others), one level in, or as the whole answer. Each field
is looked for the same way: `title` or `name`; `url` or `link`; `published_at`, `created_at` or
`created_utc`; and so on. Items wrapped as `{"data": {…}}`, like Reddit's, are looked inside.
After **Try it**, an empty field shows what was guessed, so you can type it in to keep it.

## How it reads things

- **Dates:** ISO 8601 (`2026-10-01T09:00:00Z`), email-style dates, or a number of seconds or
  milliseconds since 1970.
- **Titles and summaries:** HTML entities are unescaped and markup is taken out of summaries.
- **Links:** a relative link is made whole against the API's own address. Only web (`http`/`https`)
  links are kept.
- **Ids:** an item with no id is known by its link, or by its title and date.
- **Limits:** the newest 200 items of one answer are kept, and an answer over 5 MB is refused.

## Keys

- **One header, sent only to the API's own address.** With a key set, a redirect is refused
  rather than followed, so the key never goes anywhere else; give the address it redirects to.
- **The key is never shown again.** The box only says one is set. Leave the field empty to keep
  it, type a new one to change it, or tick **Stop sending it**.
- **Where it's kept:** in De-Algo's database, like a plugin's settings. It isn't included in your
  setup backup or in an exported group.

## When it can't be read

The run says why on the source: no list where it was told, nothing in the list with a title or
a link, an answer that isn't JSON, a refused key. The box shows the last reason under **What to
read**. Fix it, press **Try it**, and save.

**Related:** [Sources](Sources.md) · [Triggers](Triggers.md) · [Feeds](Feeds.md)
