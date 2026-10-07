"""The app was called De-Algo. What was set up, saved and written then keeps working.

Settings in the environment, the database file, sign-in cookies, plugins,
and the files the app writes and reads — group files, backups, site moves and
themes — all carry the new name now, and are read under the old one too.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from pamphlets import config


def test_a_setting_is_read_under_its_old_name_when_the_new_one_is_not_set(monkeypatch):
    monkeypatch.delenv("PAMPHLETS_LOG_LEVEL", raising=False)
    monkeypatch.setenv("DEALGO_LOG_LEVEL", "debug")
    assert config.setting("LOG_LEVEL", "INFO") == "debug"
    monkeypatch.setenv("PAMPHLETS_LOG_LEVEL", "warning")
    assert config.setting("LOG_LEVEL", "INFO") == "warning"   # the new name wins
    monkeypatch.delenv("DEALGO_LOG_LEVEL")
    monkeypatch.delenv("PAMPHLETS_LOG_LEVEL")
    assert config.setting("LOG_LEVEL", "INFO") == "INFO"


def test_an_old_database_is_moved_to_its_new_name_with_its_log_folded_in(tmp_path):
    old = tmp_path / "dealgo.sqlite3"
    connection = sqlite3.connect(old)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE kept (value TEXT)")
    connection.execute("INSERT INTO kept VALUES ('still here')")
    connection.commit()
    connection.close()

    config._adopt_old_database(tmp_path)

    assert not old.exists() and not (tmp_path / "dealgo.sqlite3-wal").exists()
    moved = sqlite3.connect(tmp_path / "pamphlets.sqlite3")
    assert moved.execute("SELECT value FROM kept").fetchall() == [("still here",)]
    moved.close()
    config._adopt_old_database(tmp_path)   # nothing left to move: nothing happens


def test_a_plugin_setting_is_read_under_its_old_name(monkeypatch):
    from pamphlets.services import plugin_settings

    monkeypatch.delenv("PAMPHLETS_PLUGIN_YOUTUBE_API_KEY", raising=False)
    monkeypatch.setenv("DEALGO_PLUGIN_YOUTUBE_API_KEY", " old-key ")
    assert plugin_settings.from_env("youtube", "api_key") == "old-key"


def test_a_plugin_finds_the_app_under_both_names():
    from tests.test_plugin_api import a_plugin, ask, probing

    found, plugin = a_plugin(
        probing("return { same = (dealgo == pamphlets), v = dealgo.version }"), frozenset()
    )
    said = ask(plugin, found, "")
    assert said["same"] is True and said["v"] == "0.1.0"


def test_old_group_files_backups_and_themes_still_load(db):
    from pamphlets.services import graph
    import importlib

    restore = importlib.import_module("pamphlets.services.backup.restore")
    from pamphlets.services.theming import theme

    with db.session_scope() as session:
        group = graph.import_group(
            session, {"de_algo_group": 3, "id": "old", "name": "Old", "nodes": [], "wires": []},
            x=0, y=0, file_name="old.json",
        )
        assert group.label == "Old"
    restore._check({"de_algo_backup": 1})          # no complaint
    with pytest.raises(restore.RestoreError):
        restore._check({"something_else": 1})
    assert theme.parse({"dealgo-theme": theme.VERSION}) is not None


def test_an_old_site_backup_is_recognised():
    from pamphlets.services.migration import sealing

    assert sealing.OLD_FORMAT == "dealgo-site-backup"
    assert sealing.FORMAT == "pamphlets-site-backup"


def test_someone_signed_in_before_the_rename_stays_signed_in(db, monkeypatch):
    from fastapi.testclient import TestClient

    from pamphlets import scheduler
    from pamphlets.services import accounts
    from pamphlets.web import app as web_app
    from tests.test_accounts import ADMIN, use_config

    use_config(monkeypatch, config.Config(
        **{**config.CONFIG.__dict__, "admin_user": ADMIN[0], "admin_password": ADMIN[1]}
    ))
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with db.session_scope() as session:
        admin = accounts.ensure_admin(session)
        token = accounts.start_session(session, admin)

    with TestClient(web_app.app) as client:
        client.cookies.set(accounts.OLD_SESSION_COOKIE, token)
        assert client.get("/settings", follow_redirects=False).status_code == 200
        client.cookies.clear()
        assert client.get("/settings", follow_redirects=False).status_code == 303
