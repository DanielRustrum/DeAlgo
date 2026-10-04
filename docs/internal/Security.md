# Security

## Threat model

| Who | Trusted with | Must not |
| --- | --- | --- |
| The operator | The host, environment, data volume | — |
| The admin account | Accounts, plugins, instance migration | Read other accounts' data |
| A member account | Their own sources, feeds, Google grant | See or change anyone else's |
| A plugin | Exactly the capabilities granted | Reach Python, files, other plugins, tokens, or other owners' data |
| A fetched archive, a feed, a web page | Nothing | Write outside its folder, execute, exhaust memory |

De-Algo is designed to sit behind a reverse proxy on a home network or a VPS, for a household or a
small group.

## Accounts and sign-in — `services/accounts/`

- **Passwords:** scrypt (N = 2¹⁴, r = 8, p = 1, 32-byte key, 16-byte salt), compared with
  `hmac.compare_digest`. 8–1024 characters for members.
- **Sessions:** `secrets.token_urlsafe(32)` in the `dealgo_session` cookie; only its SHA-256 is
  stored, so a database leak does not yield live sessions. `HttpOnly`, `SameSite=Lax`, `Secure` when
  served over HTTPS. Lifetime `DEALGO_SESSION_DAYS` (default 30). Disabling an account or resetting
  its sessions revokes them at once.
- **Admin:** from `DEALGO_ADMIN_USER`/`DEALGO_ADMIN_PASSWORD`, reconciled every start. A password
  under 8 characters is allowed (it is the operator's choice) but warned about in the log and on
  every page the admin views.
- **No sign-in configured** → no accounts at all; everyone reaching the port is the implicit owner.
  The UI says so on every page.

## Authorisation — `web/guard.py`

Middleware, default deny. Public paths are an explicit list; `/admin…` needs `is_admin`. Routes do
not take an owner from input — `owner_of(request)` only. `safe_next()` refuses off-site, `//`,
backslash and control-character redirects after login.

## Data separation

Every owned query goes through `scope.owned`. Plugins reach data only through `capabilities.acting_for`,
thread-local and set by the host. `tests/test_tenancy.py` asserts separation across routes.
See [Multi-Tenancy](Multi-Tenancy.md).

## Plugins

Code from outside the project, running in-process. Defences, in order:

1. **Admin-only install**, with every permission and its reason shown before anything is written.
2. **Two-pass load**: the manifest is read with nothing granted.
3. **Sandbox**: no `io`/`os`/`load`/`debug`/metatables, and a `require` that reads only `.lua` files in
   the plugin's own folder (name checked, path resolved and kept inside it); text chunks only; attribute filter
   blocks every Python attribute not in `LUA_OFFERS` (and all writes); 16 MiB; 10 M instructions per
   call.
4. **Capabilities** are absent unless granted and individually capped (requests, bytes, headers,
   calls, cost).
5. **Credentials never enter Lua.** `account.send` signs requests host-side, only for Google API
   hosts.
6. **Fetching** never runs git; archives are size-, count- and path-checked; only text files kept.

See [Plugin Runtime](Plugin%20Runtime.md) and [Plugin Registry](Plugin%20Registry.md).

## Secrets at rest and in transit

| Secret | Stored | In backups? |
| --- | --- | --- |
| Password hashes | `user.password_hash` | Never |
| Session tokens | SHA-256 only | Never |
| Google refresh/access tokens | `oauth_token`, plaintext in the DB | Never |
| Google client id/secret, API key | `settings`, plaintext in the DB | Never |

The database file is therefore sensitive: protect the data volume. Instance migration files are
encrypted (scrypt N = 2¹⁵ → Fernet) and still carry no secrets. See
[Backups and Migration](Backups%20and%20Migration.md).

## Web

- Jinja2 autoescaping is on for HTML templates.
- State-changing routes are POST. CSRF protection relies on `SameSite=Lax` cookies; there are no
  CSRF tokens.
- OAuth `state` is a random token checked on callback.
- **Theming** (`services/theming/`) never takes CSS. A theme is hex colours, numbers within limits
  and keys from fixed lists. `theme.parse` refuses anything else by name, and `css.py` writes the
  overrides from those checked values alone.
- **Theme pictures and the account picture** (`services/theming/images.py`), uploaded per
  account:
  - A raster picture is accepted only on a PNG, JPEG, GIF or WebP signature (3 MB at most), and
    is kept and served as that type.
  - An SVG (512 KB at most) is refused if it declares a DOCTYPE or entities. Otherwise it is
    parsed and rebuilt from an allow-list of drawing elements and presentation attributes. No
    script, style, `foreignObject`, `image`, `a` or animation survives, and nor does an `on*`
    handler, a non-local `href`, a `url()` that isn't `#…`, `javascript:` or `data:`. The cleaned
    copy is what is stored.
  - Pictures are served only to their owner, from `/settings/picture/<slot>`, with
    `X-Content-Type-Options: nosniff` and `Content-Security-Policy: default-src 'none';
    style-src 'unsafe-inline'; sandbox`, so one opened directly still runs nothing.
  - The page reaches a picture only through an address the server builds from a fixed slot name
    and a hex fingerprint.
  - A backup's pictures go through the same checks on restore.
  - The texture tiles (`static/textures/*.svg`) are the app's own: filter-drawn noise, with no
    script and no references.
  - **Fonts** (`font-body`, `font-display`, up to 4 MB) are accepted only on a WOFF2, WOFF,
    TrueType or OpenType signature, and served as that type under the same headers. They're loaded
    under a family name the server chooses (`De-Algo own body` / `De-Algo own heading`), so
    nothing from the file reaches the stylesheet. The browser's own font sanitiser checks the
    file again before drawing with it.

## Gaps

No login rate limiting, no security headers (CSP, `X-Frame-Options`), FastAPI's `/docs` enabled,
`forwarded_allow_ips="*"` trusts any proxy header. All listed with fixes in
[Known Issues](Known%20Issues.md).

## Reporting

Security problems: contact the maintainer privately rather than opening a public issue.
