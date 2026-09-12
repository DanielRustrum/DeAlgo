"""The site backup: every account, encrypted, for moving the instance.

Distinct from the per-account file in services/backup.py, which is one
account's setup in plain JSON with no credentials in it. This one carries the
things that one leaves out, which is what the encryption is for.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from dealgo.models import Channel, OAuthToken, Playlist, User
from dealgo.services import accounts, migration

PASSPHRASE = "a-long-enough-passphrase"


@pytest.fixture
def instance(db):
    """Two accounts with setups of their own, and a Google grant on one."""
    with db.session_scope() as session:
        admin = accounts.create_user(session, "admin", "admin", is_admin=True,
                                     enforce_length=False)
        sam = accounts.create_user(session, "sam", "member-password")

        for owner, feed_id, channel_id in [
            (admin.id, "PL_admin", "UCadmin"),
            (sam.id, "PL_sam", "UCsam"),
        ]:
            feed = Playlist(playlist_id=feed_id, title=f"Feed {feed_id}", owner_pk=owner)
            channel = Channel(channel_id=channel_id, title=f"Channel {channel_id}", owner_pk=owner)
            channel.playlists.append(feed)
            session.add_all([feed, channel])

        session.add(OAuthToken(owner_pk=sam.id, access_token="sams-token",
                               refresh_token="sams-refresh", account_title="Sam on YouTube"))
    return db


# -- what it holds ---------------------------------------------------------


def test_it_carries_every_account(instance):
    with instance.session_scope() as session:
        blob = migration.build_site_export(session, PASSPHRASE)
        opened = migration.open_site_export(blob, PASSPHRASE)

    names = {account["username"] for account in opened["accounts"]}
    assert names == {"admin", "sam"}


def test_each_account_keeps_its_own_setup(instance):
    with instance.session_scope() as session:
        opened = migration.open_site_export(
            migration.build_site_export(session, PASSPHRASE), PASSPHRASE
        )

    by_name = {a["username"]: a for a in opened["accounts"]}
    assert [f["playlist_id"] for f in by_name["sam"]["setup"]["feeds"]] == ["PL_sam"]
    assert [c["channel_id"] for c in by_name["admin"]["setup"]["channels"]] == ["UCadmin"]


def test_no_secret_travels_in_it(instance):
    """A migration file gets copied between machines, emailed to oneself and
    left in a Downloads folder. Nothing in it should still be worth stealing
    when it gets there."""
    with instance.session_scope() as session:
        opened = migration.open_site_export(
            migration.build_site_export(session, PASSPHRASE), PASSPHRASE
        )

    inside = json.dumps(opened)
    for secret in ("sams-token", "sams-refresh", "scrypt$", "member-password"):
        assert secret not in inside, secret

    sam = next(a for a in opened["accounts"] if a["username"] == "sam")
    assert "password_hash" not in sam
    assert "google" not in sam
    for credential in ("client_id", "client_secret", "api_key"):
        assert credential not in sam["settings"], credential


def test_it_remembers_who_will_have_to_reconnect(instance):
    """Not the grant — only that there was one, so the restore can say whose
    Google connection is missing."""
    with instance.session_scope() as session:
        opened = migration.open_site_export(
            migration.build_site_export(session, PASSPHRASE), PASSPHRASE
        )

    by_name = {a["username"]: a for a in opened["accounts"]}
    assert by_name["sam"]["had_google"] is True
    assert by_name["admin"]["had_google"] is False


# -- the encryption --------------------------------------------------------


def test_the_contents_are_not_readable_without_the_passphrase(instance):
    with instance.session_scope() as session:
        blob = migration.build_site_export(session, PASSPHRASE)

    text = blob.decode("utf-8")
    for secret in ("PL_admin", "UCsam", "sams-refresh", "scrypt$"):
        assert secret not in text, secret


def test_the_envelope_says_what_the_file_is(instance):
    """A stranger should be able to tell what they have found, and that they
    cannot open it, without learning anything from it."""
    with instance.session_scope() as session:
        envelope = json.loads(migration.build_site_export(session, PASSPHRASE))

    assert envelope["format"] == "dealgo-site-backup"
    assert envelope["accounts"] == 2
    assert envelope["kdf"]["name"] == "scrypt"
    assert "salt" in envelope["kdf"]


def test_the_wrong_passphrase_is_refused(instance):
    with instance.session_scope() as session:
        blob = migration.build_site_export(session, PASSPHRASE)

    with pytest.raises(migration.MigrationError) as raised:
        migration.open_site_export(blob, "not-the-passphrase")
    assert "does not open this file" in str(raised.value)


def test_a_file_that_has_been_altered_will_not_open(instance):
    """Fernet authenticates, so tampering is a refusal rather than a subtly
    wrong restore."""
    with instance.session_scope() as session:
        envelope = json.loads(migration.build_site_export(session, PASSPHRASE))

    payload = envelope["payload"]
    envelope["payload"] = payload[:-8] + ("A" * 8 if not payload.endswith("A" * 8) else "B" * 8)

    with pytest.raises(migration.MigrationError):
        migration.open_site_export(json.dumps(envelope).encode(), PASSPHRASE)


def test_two_backups_of_the_same_data_differ(instance):
    """A fresh salt each time, so two files never look alike."""
    with instance.session_scope() as session:
        first = json.loads(migration.build_site_export(session, PASSPHRASE))
        second = json.loads(migration.build_site_export(session, PASSPHRASE))

    assert first["kdf"]["salt"] != second["kdf"]["salt"]
    assert first["payload"] != second["payload"]


def test_a_short_passphrase_is_refused(instance):
    with instance.session_scope() as session:
        with pytest.raises(migration.MigrationError):
            migration.build_site_export(session, "short")


@pytest.mark.parametrize("rubbish", [b"", b"not json at all", b'{"format": "something-else"}'])
def test_a_file_that_is_not_one_of_ours_says_so(rubbish):
    with pytest.raises(migration.MigrationError) as raised:
        migration.open_site_export(rubbish, PASSPHRASE)
    assert "not a De-Algo site backup" in str(raised.value) or "missing the parts" in str(raised.value)


# -- moving an instance ----------------------------------------------------


def test_a_backup_restores_onto_an_empty_instance(instance, tmp_path, monkeypatch):
    """The point of the exercise: the same accounts, with the same setups, on
    a machine that had none of them."""
    with instance.session_scope() as session:
        blob = migration.build_site_export(session, PASSPHRASE)

    fresh = _fresh_instance(tmp_path, monkeypatch)
    with fresh.session_scope() as session:
        summary = migration.restore_site(session, blob, PASSPHRASE)

    assert summary.accounts == 2
    with fresh.session_scope() as session:
        names = {u.username for u in session.scalars(select(User))}
        assert names == {"admin", "sam"}

        sam = accounts.find(session, "sam")
        feeds = list(session.scalars(select(Playlist).where(Playlist.owner_pk == sam.id)))
        assert [f.playlist_id for f in feeds] == ["PL_sam"]

        # And nothing came with them that should not have.
        assert session.scalar(select(OAuthToken).where(OAuthToken.owner_pk == sam.id)) is None


def test_a_restored_account_cannot_be_signed_in_to_yet(instance, tmp_path, monkeypatch):
    """No password came across, so nothing opens it until the admin sets one.
    An account that arrived signable-in would mean the file was a credential."""
    with instance.session_scope() as session:
        blob = migration.build_site_export(session, PASSPHRASE)

    fresh = _fresh_instance(tmp_path, monkeypatch)
    with fresh.session_scope() as session:
        migration.restore_site(session, blob, PASSPHRASE)
        moved = accounts.find(session, "sam")

        assert not accounts.verify_password("member-password", moved.password_hash)
        assert not accounts.verify_password("", moved.password_hash)
        assert not accounts.verify_password(migration.NO_PASSWORD, moved.password_hash)
        with pytest.raises(accounts.AccountError):
            accounts.authenticate(session, "sam", "member-password")


def test_the_admin_sets_a_password_and_then_they_can(instance, tmp_path, monkeypatch):
    with instance.session_scope() as session:
        blob = migration.build_site_export(session, PASSPHRASE)

    fresh = _fresh_instance(tmp_path, monkeypatch)
    with fresh.session_scope() as session:
        migration.restore_site(session, blob, PASSPHRASE)
        moved = accounts.find(session, "sam")
        accounts.set_password(session, moved, "a-new-password")

        assert accounts.authenticate(session, "sam", "a-new-password").username == "sam"


def test_the_restore_says_what_is_still_missing(instance, tmp_path, monkeypatch):
    """A restore that looks complete and is not is worse than one that says
    what is left to do."""
    with instance.session_scope() as session:
        blob = migration.build_site_export(session, PASSPHRASE)

    fresh = _fresh_instance(tmp_path, monkeypatch)
    with fresh.session_scope() as session:
        summary = migration.restore_site(session, blob, PASSPHRASE)

    notes = " ".join(summary.notes)
    assert "Set a password for" in notes and "sam" in notes
    assert "connect it again" in notes          # and who had a Google account


def test_the_admin_of_the_new_machine_stays_its_own(instance, tmp_path, monkeypatch):
    """An account marked admin in a file must not become one here: the admin
    is whatever DEALGO_ADMIN_USER says, on this machine."""
    with instance.session_scope() as session:
        blob = migration.build_site_export(session, PASSPHRASE)

    fresh = _fresh_instance(tmp_path, monkeypatch)
    with fresh.session_scope() as session:
        migration.restore_site(session, blob, PASSPHRASE)
        assert accounts.find(session, "admin").is_admin is False


def test_restoring_twice_does_not_double_anything(instance, tmp_path, monkeypatch):
    with instance.session_scope() as session:
        blob = migration.build_site_export(session, PASSPHRASE)

    fresh = _fresh_instance(tmp_path, monkeypatch)
    with fresh.session_scope() as session:
        migration.restore_site(session, blob, PASSPHRASE)
    with fresh.session_scope() as session:
        again = migration.restore_site(session, blob, PASSPHRASE)

    assert again.accounts == 0            # both were already here
    assert any("already here" in note for note in again.notes)
    with fresh.session_scope() as session:
        assert len(list(session.scalars(select(User)))) == 2
        assert len(list(session.scalars(select(Playlist)))) == 2


def _fresh_instance(tmp_path, monkeypatch):
    """A second database, standing in for the machine being moved to."""
    from dealgo import config, db as db_module

    path = tmp_path / "elsewhere.sqlite3"
    elsewhere = config.Config(**{**config.CONFIG.__dict__, "database_url": f"sqlite:///{path}"})
    monkeypatch.setattr(config, "CONFIG", elsewhere)
    monkeypatch.setattr(db_module, "CONFIG", elsewhere)
    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(db_module, "_SessionFactory", None)
    db_module.init_db()
    return db_module
