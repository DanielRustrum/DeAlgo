"""Connecting a Google account, and disconnecting it."""

from __future__ import annotations

import datetime as dt
import secrets
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from ... import outgoing
from ...config import CONFIG
from ...db import session_scope
from ...plugins.publisher import PublishError
from ...services import oauth
from ...services.auth import (
    build_client,
    client_credentials,
    disconnect,
    store_token,
)
from ..responses import is_htmx, owner_of, redirect

if TYPE_CHECKING:
    pass

router = APIRouter()


# OAuth state tokens live in memory: the flow completes in seconds, and a
# restart mid-flow should invalidate it anyway.
_oauth_states: dict[str, float] = {}


@router.get("/oauth/start")
def oauth_start(request: Request) -> Response:
    """Send the browser to Google to ask for consent."""
    with session_scope() as session:
        client_id, client_secret = client_credentials(session)
    if not (client_id and client_secret):
        return redirect("/settings", err="Add a Google OAuth client id and secret first.")

    state = secrets.token_urlsafe(24)
    _oauth_states[state] = dt.datetime.now(dt.timezone.utc).timestamp()
    url = oauth.build_authorization_url(client_id, CONFIG.redirect_uri, state)
    if is_htmx(request):
        # An XHR cannot follow a redirect to another origin, so hand the URL
        # back and let htmx navigate the whole window to it.
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


@router.get("/oauth/callback")
def oauth_callback(
    request: Request, code: str = "", state: str = "", error: str = ""
) -> RedirectResponse:
    """Where Google sends the browser back: store the grant for this account."""
    # Google sends the browser back here, so the session cookie says which
    # account the grant belongs to.
    owner = owner_of(request)
    if error:
        explanations = {
            "access_denied": (
                "Google refused the request. Either you declined it, or this account is not on the "
                "OAuth client's test-user list while the consent screen is still in Testing."
            ),
            "redirect_uri_mismatch": (
                f"The OAuth client has no redirect URI matching {CONFIG.redirect_uri} — add it "
                "exactly, including the scheme and port."
            ),
        }
        return redirect("/settings", err=explanations.get(error, f"Google returned an error: {error}"))
    if not code:
        return redirect("/settings", err="Google did not return an authorization code.")

    issued = _oauth_states.pop(state, None)
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    # Drop anything stale so the dict cannot grow without bound.
    for key, value in list(_oauth_states.items()):
        if now - value > 600:
            _oauth_states.pop(key, None)
    if issued is None or now - issued > 600:
        return redirect("/settings", err="That sign-in link expired. Try connecting again.")

    with session_scope() as session, outgoing.client() as http:
        client_id, client_secret = client_credentials(session)
        try:
            token = oauth.exchange_code(
                code=code,
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=CONFIG.redirect_uri,
                client=http,
            )
        except oauth.OAuthError as exc:
            return redirect("/settings", err=f"Could not complete sign-in: {exc}")

        store_token(session, token, owner=owner)
        client = build_client(session, http)
        try:
            account = client.account_name()
        except PublishError:
            account = None
        if account:
            store_token(session, token, account_title=account, owner=owner)
    return redirect("/settings", ok="Google account connected.")


@router.post("/oauth/disconnect")
def oauth_disconnect() -> RedirectResponse:
    """Revoke and forget the Google grant (the implicit owner's — see Known Issues)."""
    with session_scope() as session, outgoing.client() as http:
        disconnect(session, http)
    return redirect("/settings", ok="Google account disconnected.")
