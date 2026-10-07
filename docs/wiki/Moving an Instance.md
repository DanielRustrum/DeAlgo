# Moving an Instance

**Admin → Move this instance** saves every account and its setup in one encrypted file, for standing
Pamphlets up on another machine. Admin only.

## Exporting

Choose a passphrase of at least 12 characters. **It is the only way to open the file** — there is no
recovery.

Anyone holding the file can see that it is a Pamphlets backup, when it was made and how many accounts
it holds. Nothing else is readable. The file is authenticated: an altered file refuses to open.

## What travels

- Every account's username, and each account's setup — the same contents as a
  [setup file](Backup%20and%20Restore.md), with the same gaps.
- **No secrets:** no password hashes, no Google grants, no API keys.

## Restoring

Load the file on the new machine and enter the passphrase.

- Accounts that do not exist are created **without a password**. Set one for each under Admin before
  they can sign in. Each account reconnects its own Google account.
- Each account's setup is merged into its own space. Nothing existing is deleted; restoring twice
  changes nothing.
- An account marked admin in the file is restored as a member. The admin always comes from
  `PAMPHLETS_ADMIN_USER`.

## Moving everything instead

Because the setup file does not yet carry the canvas or non-YouTube sources, the reliable way to
move a whole instance is to copy the database file — see [Backup and Restore](Backup%20and%20Restore.md).

**Related:** [Accounts](Accounts.md) · [Backup and Restore](Backup%20and%20Restore.md)
