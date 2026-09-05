"""Credential resolution: settings override environment, tokens self-refresh."""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from ..config import CONFIG
from ..db import get_settings, get_token
from ..models import OAuthToken, to_naive_utc, utcnow
from ..youtube import oauth
from ..youtube.api import YouTubeClient

log = logging.getLogger(__name__)


def client_credentials(session: Session) -> tuple[str, str]:
    """The Google OAuth client id/secret, from settings or the environment."""
    settings = get_settings(session)
    return (
        (settings.client_id or CONFIG.client_id or "").strip(),
        (settings.client_secret or CONFIG.client_secret or "").strip(),
    )


def api_key(session: Session) -> str:
    settings = get_settings(session)
    return (settings.api_key or CONFIG.api_key or "").strip()


def has_client_credentials(session: Session) -> bool:
    client_id, client_secret = client_credentials(session)
    return bool(client_id and client_secret)


def valid_access_token(session: Session, http: httpx.Client) -> str | None:
    """Return a usable access token, refreshing and persisting it if stale."""
    token = get_token(session)
    if token is None:
        return None
    if not token.is_expired():
        return token.access_token

    if not token.refresh_token:
        token.refresh_error = "No refresh token is stored."
        session.flush()
        log.warning("access token expired and no refresh token is stored; reconnect required")
        return None

    client_id, client_secret = client_credentials(session)
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


def build_client(session: Session, http: httpx.Client) -> YouTubeClient:
    """A client with whatever credentials are available (possibly none).

    Every request it makes is charged to the day's quota ledger.
    """
    from .quota import meter

    return YouTubeClient(
        http=http,
        access_token=valid_access_token(session, http),
        api_key=api_key(session),
        meter=meter(session),
    )


def store_token(session: Session, response: oauth.TokenResponse, *, account_title: str | None = None) -> OAuthToken:
    token = get_token(session)
    if token is None:
        token = OAuthToken(id=1, access_token=response.access_token)
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
    token = get_token(session)
    if token is None:
        return
    oauth.revoke(token.refresh_token or token.access_token, http)
    session.delete(token)
