"""The OAuth 2.0 authorization-code flow, for whichever service asks.

Writing back to a service acts on behalf of a person, so a key is not enough:
it needs that person's grant. Where to ask, where to trade the code and which
scopes to ask for are the plugin's — its `connect` table (registry/connect.py)
— and the flow itself is the same for every service, so it lives here. The
refresh token is kept, so the browser dance happens once.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from ..plugins.registry.connect import Connect

#: One decoded JSON object from the service. Keys are strings; nothing about the
#: values is known until the code reading them checks. `Any` inside is
#: honesty at a boundary, not a gap.
JsonDict = dict[str, Any]

class OAuthError(RuntimeError):
    """The service refused, or answered with something that is not a token."""

    pass


@dataclass(frozen=True)
class TokenResponse:
    """A granted access token, and the refresh token to renew it with."""

    access_token: str
    refresh_token: str | None
    expires_at: dt.datetime
    scope: str | None


def build_authorization_url(
    connect: Connect, client_id: str, redirect_uri: str, state: str
) -> str:
    """Where to send the browser to ask the service for consent.

    The plugin's own parameters first, then the ones the flow needs, so a
    plugin cannot point the code at another address or drop the state.
    """
    params = {
        **dict(connect.params),
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(connect.scopes),
        "state": state,
    }
    joiner = "&" if "?" in connect.authorize else "?"
    return f"{connect.authorize}{joiner}{urlencode(params)}"


def _to_token_response(payload: JsonDict, fallback_refresh: str | None = None) -> TokenResponse:
    """A `TokenResponse` from the service's JSON, keeping `fallback_refresh` if none came."""
    if "access_token" not in payload:
        raise OAuthError(payload.get("error_description") or payload.get("error") or "no access_token in response")
    expires_in = int(payload.get("expires_in", 3600))
    return TokenResponse(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token") or fallback_refresh,
        expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=expires_in),
        scope=payload.get("scope"),
    )


def _post(connect: Connect, client: httpx.Client, data: dict[str, str]) -> JsonDict:
    """POST to the service's token endpoint; raises `OAuthError` on any refusal."""
    response = client.post(connect.token, data=data, headers={"Accept": "application/json"})
    try:
        payload = response.json()
    except ValueError:
        raise OAuthError(f"token endpoint returned {response.status_code}: {response.text[:200]}") from None
    if response.status_code >= 400:
        raise OAuthError(payload.get("error_description") or payload.get("error") or f"HTTP {response.status_code}")
    return dict(payload)


def exchange_code(
    connect: Connect,
    *, code: str, client_id: str, client_secret: str, redirect_uri: str, client: httpx.Client,
) -> TokenResponse:
    """Trade the code from the consent redirect for an access and a refresh token."""
    payload = _post(
        connect,
        client,
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    return _to_token_response(payload)


def refresh_access_token(
    connect: Connect,
    *, refresh_token: str, client_id: str, client_secret: str, client: httpx.Client,
) -> TokenResponse:
    """A fresh access token, from the stored refresh token."""
    payload = _post(
        connect,
        client,
        {
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        },
    )
    return _to_token_response(payload, fallback_refresh=refresh_token)


def revoke(connect: Connect, token: str, client: httpx.Client) -> None:
    """Ask the service to revoke a token, where it offers to. Best effort:
    disconnecting never fails on this."""
    if not connect.revoke:
        return
    try:
        client.post(connect.revoke, data={"token": token})
    except httpx.HTTPError:
        # Local disconnect should succeed even if the service is unreachable.
        pass
