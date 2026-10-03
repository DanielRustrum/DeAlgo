"""Signing in to a plugin's service: its credentials, and each account's token.

A plugin that writes back as a person declares how its service signs people in
(its `connect`, registry/connect.py). The OAuth client it needs is in its own
settings for everyone, which the admin sets on its card; each account then
connects its own sign-in, and the token is kept here, refreshed here and
attached to the plugin's requests here — never handed to the plugin.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import OAuthToken, to_naive_utc, utcnow
from ..plugins import registry
from ..plugins.publisher import Publisher, publishing_plugin
from ..plugins.registry.plugin import Plugin
from . import oauth, plugin_settings
from .scope import OwnerId, belongs_to

log = logging.getLogger(__name__)


def connecting(plugin_id: str) -> Plugin | None:
    """The working plugin with this id, if it declares a sign-in."""
    found = next((p for p in registry.current().working if p.id == plugin_id), None)
    return found if found is not None and found.connect is not None else None


def every_connecting() -> list[Plugin]:
    """Every working plugin that declares a sign-in, in the registry's order."""
    return [p for p in registry.current().working if p.connect is not None]


def publisher_id() -> str:
    """The id of the plugin that publishes, or "" when none does."""
    found = publishing_plugin()
    return found.id if found is not None else ""


def _app(plugin: Plugin, name: str) -> str:
    """One of the plugin's app settings, as text: saved, environment, or default."""
    if not name:
        return ""
    declared = plugin.settings.named("app", name)
    value = plugin_settings.app_value(plugin.id, name)
    if value is None:
        value = declared.default if declared is not None else ""
    return value.strip()


def client_credentials(plugin: Plugin) -> tuple[str, str]:
    """The OAuth client id and secret the admin gave this plugin."""
    if plugin.connect is None:
        return "", ""
    return _app(plugin, plugin.connect.client_id), _app(plugin, plugin.connect.client_secret)


def api_key(plugin: Plugin) -> str:
    """The key the plugin's service reads with when nobody is signed in, if any."""
    if plugin.connect is None:
        return ""
    return _app(plugin, plugin.connect.api_key)


def has_client_credentials(plugin: Plugin) -> bool:
    """Whether the admin has given this plugin an OAuth client to sign in with."""
    client_id, client_secret = client_credentials(plugin)
    return bool(client_id and client_secret)


def get_token(session: Session, owner: OwnerId, plugin_id: str) -> OAuthToken | None:
    """This account's sign-in to one plugin's service."""
    return session.scalar(
        select(OAuthToken)
        .where(belongs_to(OAuthToken, owner))
        .where(OAuthToken.provider == plugin_id)
    )


def publisher_token(session: Session, owner: OwnerId) -> OAuthToken | None:
    """This account's sign-in to the service that feeds can be published to."""
    found = publisher_id()
    return get_token(session, owner, found) if found else None


def valid_access_token(
    session: Session, http: httpx.Client, owner: OwnerId, plugin: Plugin
) -> str | None:
    """A usable access token for this account, refreshed and stored if stale."""
    if plugin.connect is None:
        return None
    token = get_token(session, owner, plugin.id)
    if token is None:
        return None
    if not token.is_expired():
        return token.access_token

    if not token.refresh_token:
        token.refresh_error = "No refresh token is stored."
        session.flush()
        log.warning("%s: access token expired and no refresh token is stored", plugin.title)
        return None

    client_id, client_secret = client_credentials(plugin)
    if not (client_id and client_secret):
        log.warning("%s: cannot refresh the sign-in: no OAuth client is set", plugin.title)
        return None

    try:
        refreshed = oauth.refresh_access_token(
            plugin.connect,
            refresh_token=token.refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            client=http,
        )
    except oauth.OAuthError as exc:
        # The grant is gone for good; say so instead of reporting "connected"
        # while every sync quietly declines to write anything.
        token.refresh_error = str(exc)
        session.flush()
        log.error("%s: refreshing the sign-in failed: %s", plugin.title, exc)
        return None

    token.access_token = refreshed.access_token
    token.refresh_token = refreshed.refresh_token or token.refresh_token
    token.expires_at = to_naive_utc(refreshed.expires_at)
    token.scope = refreshed.scope or token.scope
    token.refresh_error = None
    token.updated_at = utcnow()
    session.flush()
    log.info("%s: refreshed the access token", plugin.title)
    return token.access_token


def build_client(session: Session, http: httpx.Client, owner: OwnerId = None) -> Publisher:
    """A way to write back for this account, if it has anything to write with.

    It holds no credential and knows no endpoints. What it knows is whether
    there is a sign-in and a key here; everything past that is the plugin's,
    and the token is attached on the way out by the host, never handed over.
    """
    plugin = publishing_plugin()
    if plugin is None or plugin.connect is None:
        return Publisher(owner, writable=False, readable=False)
    token = valid_access_token(session, http, owner, plugin)
    return Publisher(
        owner,
        writable=bool(token),
        readable=bool(token or api_key(plugin)),
    )


def store_token(
    session: Session,
    response: oauth.TokenResponse,
    *,
    plugin_id: str,
    account_title: str | None = None,
    owner: OwnerId = None,
) -> OAuthToken:
    """Save a granted token for this account and service, replacing any it had."""
    token = get_token(session, owner, plugin_id)
    if token is None:
        token = OAuthToken(owner_pk=owner, provider=plugin_id, access_token=response.access_token)
        session.add(token)
    token.access_token = response.access_token
    if response.refresh_token:
        token.refresh_token = response.refresh_token
    token.expires_at = to_naive_utc(response.expires_at)
    token.scope = response.scope
    token.refresh_error = None
    if account_title:
        token.account_title = account_title
    token.updated_at = utcnow()
    session.flush()
    return token


def disconnect(session: Session, http: httpx.Client, owner: OwnerId, plugin: Plugin) -> None:
    """Revoke this account's sign-in with the service and forget it."""
    token = get_token(session, owner, plugin.id)
    if token is None:
        return
    if plugin.connect is not None:
        oauth.revoke(plugin.connect, token.refresh_token or token.access_token, http)
    session.delete(token)
