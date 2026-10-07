# The dealgo Object

`dealgo` is always in a plugin's world. It is how a plugin reads and changes the setup of the account
it is working for.

| Member | Permission | Returns |
| --- | --- | --- |
| `dealgo.version` | none | Pamphlets's version, e.g. `"0.1.0"`. A value, not a function. |
| `dealgo.permissions()` | none | Your permissions — see [Permissions](Permissions.md). |
| `dealgo.sources()` | `read` | A list of `{ key, title, kind, enabled }`. |
| `dealgo.feeds()` | `read` | A list of `{ title, generic, enabled, sources }` — `sources` is a count. |
| `dealgo.watch(reference)` | `manage` | Starts watching `reference`, as if typed by the user. Returns its key, or `nil`. |
| `dealgo.pause(key, on)` | `manage` | Sets the source's **on** state to `on`: `pause(key, false)` switches it off, `pause(key, true)` on. Returns `true` if found. |

Lists hold at most 500 rows.

## Whose account

A plugin is shared by every account, so `dealgo` has no account of its own. It answers only while
Pamphlets is doing work for an account:

- inside `keep` and `rank`,
- inside a source's `posts`,
- inside [publisher](Publishing.md) functions.

Everywhere else — while loading, in `recognise`, `accept`, `refine`, `home`, `item_url` and
`mirror` — it answers nothing: empty lists, `nil`, `false`. The same rule applies to
[`account`](Account.md). This is what stops one account's data leaking into another's.

## Notes

- `watch` checks the reference the same way the canvas does, so it may make a network request. What it
  adds arrives **paused**: a plugin can suggest, not start fetching.
- `watch` adds a source; it does not put a box on the canvas. The user wires it.
- Nothing here can delete anything.

**Related:** [Permissions](Permissions.md) · [Account](Account.md)
