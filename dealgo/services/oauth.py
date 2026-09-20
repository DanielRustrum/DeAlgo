"""Google OAuth 2.0 authorization-code flow.

Writing to a playlist acts on behalf of a person, so an API key is not enough:
De-Algo needs a user grant. The refresh token is persisted, so the browser dance
happens exactly once.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

#: One decoded JSON object from Google. Keys are strings; nothing about the
#: values is known until the code reading them checks. `Any` inside is
#: honesty at a boundary, not a gap.
JsonDict = dict[str, Any]

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

# Full youtube scope: playlistItems.insert/delete need write access.
SCOPES = ("https://www.googleapis.com/auth/youtube",)


class OAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    refresh_token: str | None
    expires_at: dt.datetime
    scope: str | None


def build_authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        # Force a refresh token even on re-authorization.
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def _to_token_response(payload: JsonDict, fallback_refresh: str | None = None) -> TokenResponse:
    if "access_token" not in payload:
        raise OAuthError(payload.get("error_description") or payload.get("error") or "no access_token in response")
    expires_in = int(payload.get("expires_in", 3600))
    return TokenResponse(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token") or fallback_refresh,
        expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=expires_in),
        scope=payload.get("scope"),
    )


def _post(client: httpx.Client, data: dict[str, str]) -> JsonDict:
    response = client.post(TOKEN_ENDPOINT, data=data)
    try:
        payload = response.json()
    except ValueError:
        raise OAuthError(f"token endpoint returned {response.status_code}: {response.text[:200]}") from None
    if response.status_code >= 400:
        raise OAuthError(payload.get("error_description") or payload.get("error") or f"HTTP {response.status_code}")
    return dict(payload)


def exchange_code(
    *, code: str, client_id: str, client_secret: str, redirect_uri: str, client: httpx.Client
) -> TokenResponse:
    payload = _post(
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
    *, refresh_token: str, client_id: str, client_secret: str, client: httpx.Client
) -> TokenResponse:
    payload = _post(
        client,
        {
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        },
    )
    return _to_token_response(payload, fallback_refresh=refresh_token)


def revoke(token: str, client: httpx.Client) -> None:
    try:
        client.post(REVOKE_ENDPOINT, data={"token": token})
    except httpx.HTTPError:
        # Local disconnect should succeed even if Google is unreachable.
        pass
