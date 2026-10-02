# Backups and Migration

Two deliberately different things.

| | Per-account backup | Instance migration |
| --- | --- | --- |
| Code | `services/backup/` | `services/migration/` |
| Who | Any account, for itself (Settings) | Admin only (`/admin/backup`, `/admin/restore`) |
| Covers | One account's feeds and sources | Every account and its setup |
| Format | Plain JSON, `de_algo_backup: 1` | Encrypted blob, `dealgo-site-backup` v1 |
| Secrets | None | None |
| Purpose | Keep and restore your own setup | Move the whole instance to another machine |

## Per-account backup

**Export** (`build_export`): settings subset, feeds (`playlist_id`, title, enabled, priority,
caps, wired channel ids), sources (`channel_id`, title, handle, legacy filter columns, timestamps,
feed ids), counts.

Rows reference each other by **service ids** (channel id, playlist id), never primary keys, so a file
means the same on a database numbered differently.

**Restore** (`restore`): validate the marker and version; upsert feeds and sources by id; reattach
memberships. Additive — nothing is deleted. `last_checked_at` is restored only if the file also
carries items, otherwise a restored source would treat its whole feed as new. Older files carrying
items, placements or a client id still restore.

**Not in it today:** the canvas (nodes, wires, pieces, triggers, positions), `source_kind`,
`source_url`, `mirror_url`. See [Known Issues](Known%20Issues.md).

## Instance migration

**Export** (`build_site_export(passphrase)`):

1. For every user, plus the implicit owner if it has data: username, `is_admin`, `enabled`, the
   per-account `setup` (as above), settings (no credentials), and `had_google`.
2. JSON → encrypted: 16-byte random salt; key = scrypt(passphrase, N = 2¹⁵, r = 8, p = 1) → Fernet
   (AES-128-CBC + HMAC-SHA256). Salt travels in the clear beside the ciphertext. Passphrase ≥ 12
   characters.

**Restore** (`restore_site`): decrypt (a wrong passphrase or tampered file fails, never half-restores);
create or match users by name, **without passwords** — the admin sets new ones; apply settings; run
the per-account `restore` for each setup. Each person reconnects Google themselves.

Losing the passphrase loses the file. No recovery, by design.

## Why no secrets travel

Backup files live in Downloads folders and email for years. Password hashes, Google tokens, client
secrets and API keys are all re-enterable in a minute, and any that had travelled would need rotating
anyway.

## The whole database

For a full-fidelity copy (canvas included), stop the container and copy the data volume. That
includes secrets: treat it accordingly. See the wiki's
[Moving an Instance](../wiki/Moving%20an%20Instance.md).
