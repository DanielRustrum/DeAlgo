# Accounts

De-Algo has no sign-in until you give it an admin. Until then, anyone who can reach the address can
use it, and a banner on every page says so.

## Turning sign-in on

Set both variables and restart:

```bash
DEALGO_ADMIN_USER=rusty
DEALGO_ADMIN_PASSWORD=something-long
```

The admin account comes from the environment and is re-read on every start:

- **Lost the password?** Change the variable and restart.
- **The admin cannot change its own password in the app** — the environment owns it.
- **Rename the variable** and the old admin becomes an ordinary member.
- A password under 8 characters is allowed here (e.g. `admin`/`admin` for trying it out), with a
  warning in the log and on every page. Accounts made in the app always need 8 or more.

## Members

The admin creates everyone else under **Admin → Accounts**, and can:

- set a new password,
- switch an account off,
- sign it out of every browser,
- delete it.

Switching off, deleting or changing a password ends that account's sessions immediately.

## What is whose

Every account is private. Each has its own sources, feeds, canvas, [Settings](Settings.md) and
sign-ins to plugins' services. The admin cannot see other accounts' setups. A plugin's settings for
everyone, and its service's daily [quota](Quota.md), are shared by the whole install.

The admin alone manages **accounts**, [plugins](Plugins.md) and
[moving the instance](Moving%20an%20Instance.md). Plugins are shared: one install, one set of plugins.

## Algorithms

Under **Admin → Algorithms**, the admin can switch everyone's [algorithm](Nodes/Aggregation.md) off.
Each account's algorithm learns and predicts on this machine's processor, on every run; on a small
machine that can be more than it should carry. Switched off, Aggregation pieces do nothing and nothing
is learned. What Focus mode remembers is kept, so switching back on picks up where it was.

## How it is secured

- Passwords are stored as **scrypt** hashes with a per-password salt.
- A sign-in is a random token in an `HttpOnly`, `SameSite=Lax` cookie, `Secure` over HTTPS. Only its
  SHA-256 is stored, so a copy of the database cannot be used to sign in.
- A wrong username and a wrong password get the same answer, in the same time.
- Cross-site form posts are blocked by `SameSite=Lax`. There are no per-form CSRF tokens.

**Related:** [Environment Variables](Environment%20Variables.md) · [Settings](Settings.md)
