"""Credential resolution: settings override environment, tokens self-refresh."""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from ..config import CONFIG
from ..db import get_settings, get_token
from ..models import OAuthToken, to_naive_utc, utcnow
from ..plugins.publisher import Publisher
from . import oauth
from .scope import OwnerId

log = logging.getLogger(__name__)


def client_credentials(session: Session, owner: OwnerId = None) -> tuple[str, str]:
    """This account's Google OAuth client id/secret, or the environment's."""
    settings = get_settings(session, owner)
    return (
        (settings.client_id or CONFIG.client_id or "").strip(),
        (settings.client_secret or CONFIG.client_secret or "").strip(),
    )


def api_key(session: Session, owner: OwnerId = None) -> str:
    """This account's Google API key, or the environment's."""
    settings = get_settings(session, owner)
    return (settings.api_key or CONFIG.api_key or "").strip()


def has_client_credentials(session: Session, owner: OwnerId = None) -> bool:
    """Whether a Google OAuth client id and secret are set for this account."""
    client_id, client_secret = client_credentials(session, owner)
    return bool(client_id and client_secret)


def valid_access_token(
    session: Session, http: httpx.Client, owner: OwnerId = None
) -> str | None:
    """A usable access token for this account, refreshed and stored if stale."""
    token = get_token(session, owner)
    if token is None:
        return None
    if not token.is_expired():
        return token.access_token

    if not token.refresh_token:
        token.refresh_error = "No refresh token is stored."
        session.flush()
        log.warning("access token expired and no refresh token is stored; reconnect required")
        return None

    client_id, client_secret = client_credentials(session, owner)
    if not (client_id and client_secret):
        log.warning("cannot refresh access token: no OAuth client configured")
        return None

    try:
        refreshed = oauth.refresh_access_token(
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
        log.error("token refresh failed: %s", exc)
        return None

    token.access_token = refreshed.access_token
    token.refresh_token = refreshed.refresh_token or token.refresh_token
    token.expires_at = to_naive_utc(refreshed.expires_at)
    token.scope = refreshed.scope or token.scope
    token.refresh_error = None
    token.updated_at = utcnow()
    session.flush()
    log.info("refreshed Google access token")
    return token.access_token


def build_client(session: Session, http: httpx.Client, owner: OwnerId = None) -> Publisher:
    """A way to write back for this account, if it has anything to write with.

    It holds no credential and knows no endpoints. What it knows is whether
    there is a sign-in and a key here; everything past that is the plugin's,
    and the token is attached on the way out by the host, never handed over.

    Every request it causes is charged to this account's own quota ledger:
    each brings its own Google project, so each spends its own allowance.
    """
    token = valid_access_token(session, http, owner)
    return Publisher(
        owner,
        writable=bool(token),
        readable=bool(token or api_key(session, owner)),
    )


def store_token(
    session: Session,
    response: oauth.TokenResponse,
    *,
    account_title: str | None = None,
    owner: OwnerId = None,
) -> OAuthToken:
    """Save a granted token for this account, replacing any it had."""
    token = get_token(session, owner)
    if token is None:
        token = OAuthToken(owner_pk=owner, access_token=response.access_token)
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


def disconnect(session: Session, http: httpx.Client) -> None:
    """Revoke the Google grant with Google and forget it.

    Takes no owner, so it acts on the implicit owner's grant — see Known Issues.
    """
    token = get_token(session)
    if token is None:
        return
    oauth.revoke(token.refresh_token or token.access_token, http)
    session.delete(token)
