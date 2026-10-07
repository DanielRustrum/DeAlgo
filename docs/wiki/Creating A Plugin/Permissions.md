# Permissions

A plugin starts with pure Lua and the [`pamphlets`](The%20pamphlets%20Object.md) object, nothing else.
Everything more is asked for by name, with a reason, and granted by the admin.

## Asking

```lua
permissions = {
  { name = "network", why = "To read an account page for its posts." },
  { name = "clock",   why = "To date posts that only say how long ago they were made." },
},
```

`why` is required and shown to the admin word for word (up to 400 characters). Say plainly what it is
for. Asking for the same permission twice is an error.

## The vocabulary

| `name` | Grants | Documented in |
| --- | --- | --- |
| `network` | The `net` object: fetch web pages | [Network](Network.md) |
| `clock` | The `clock` object: the current time | [Clock and Log](Clock%20and%20Log.md) |
| `log` | The `log` object: write to Pamphlets's log | [Clock and Log](Clock%20and%20Log.md) |
| `read` | `pamphlets.sources()` and `pamphlets.feeds()` answer | [The pamphlets Object](The%20pamphlets%20Object.md) |
| `manage` | `pamphlets.watch()` and `pamphlets.pause()` work | [The pamphlets Object](The%20pamphlets%20Object.md) |
| `account` | The `account` object: requests to Google as the connected account | [Account](Account.md) |

A name not in this list is shown to the admin as unknown and can never be granted.

## Granted or not

The admin can untick any permission, now or later. A plugin must work — perhaps doing less — without
any of them.

A permission not granted is **absent**, not locked: there is simply no `net` (or `clock`, `log`,
`account`) in the plugin's world. Test for it:

```lua
if net then
  -- fetch something
end
```

`read` and `manage` are different: `pamphlets` is always there, and its functions answer nothing
(empty lists, `nil`, `false`) without them.

## Reading your own grants

`pamphlets.permissions()` returns what you asked for and how it went — useful to explain yourself:

```lua
for _, p in ipairs(pamphlets.permissions()) do
  -- p.name, p.label, p.why, p.granted (boolean), p.known (boolean)
end
```

`known` is `false` for a permission this version of Pamphlets does not have.

## Shipped plugins

Plugins shipped with Pamphlets start with everything they asked for. Plugins added by the admin start
with whatever was ticked at install.

**Related:** [The Sandbox](The%20Sandbox.md) · [The pamphlets Object](The%20pamphlets%20Object.md)
