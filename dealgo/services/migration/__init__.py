"""The whole instance, encrypted, for moving it to another machine.

This is the other half of the backup story, and deliberately a different thing
from the per-account file:

* **A per-account backup** (services/backup.py) is the shape of one account's
  setup — its feeds and channels — in plain JSON, with no credentials in it,
  meant to be read, kept and restored by the person it belongs to.
* **This** is every account and every setup at once: who the accounts are,
  what each of them watches, and how each of them is configured. It exists to
  stand the same instance up somewhere else.

**No secrets travel in it.** Not password hashes, not Google grants, not API
keys. A migration file is a thing that gets copied between machines, emailed to
oneself and left in a Downloads folder, and a credential that has been through
all that is a credential to be rotated anyway. So the accounts come across and
the passwords do not: the admin sets a new one for each from the Admin page,
and each account reconnects its own Google when it next signs in.

It is still encrypted, because everyone's usernames and everything they watch
is nobody else's business. The passphrase the admin chooses is stretched with
scrypt (the same function passwords use here) and handed to Fernet, which is
authenticated: a file that has been altered fails to open rather than restoring
something subtly wrong. The salt travels in the clear beside the ciphertext,
as it must.

Losing the passphrase means losing the file. There is no recovery, by design.
"""

from __future__ import annotations

from .export import build_site_export, filename
from .restore import NO_PASSWORD, restore_site
from .sealing import MIN_PASSPHRASE, MigrationError, check_passphrase, open_site_export

__all__ = [
    "build_site_export",
    "check_passphrase",
    "filename",
    "MigrationError",
    "MIN_PASSPHRASE",
    "NO_PASSWORD",
    "open_site_export",
    "restore_site",
]
