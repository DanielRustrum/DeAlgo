"""Signing in to a plugin's service, and signing out of it.

The plugin says how its service signs people in (its `connect`); these routes
do it. One callback address for every service, so the address registered with
a service never changes: which sign-in came back is in the `state`, which this
made and remembers.
"""

from __future__ import annotations

import datetime as dt
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from ... import outgoing
from ...config import CONFIG
from ...db import session_scope
from ...plugins.publisher import PublishError, publishing_plugin
from ...plugins.registry.plugin import Plugin
from ...services import connections, oauth
from ...services import quota as quota_service
from ...services.scope import OwnerId
from ..responses import is_htmx, owner_of, redirect
from ..templates import Context

router = APIRouter()

#: How long a sign-in may take, from leaving to coming back.
STATE_SECONDS = 600

# Sign-in states live in memory, by the state token: which plugin, and when.
# The flow completes in seconds, and a restart mid-flow should invalidate it.
_states: dict[str, tuple[str, float]] = {}


def connection_view(session: Session, owner: OwnerId, plugin: Plugin) -> Context | None:
    """One plugin's sign-in as its block under Settings shows it; None without one."""
    connect = plugin.connect
    if connect is None:
        return None
    token = connections.get_token(session, owner, plugin.id)
    allowance = quota_service.state(session, plugin.id) if connect.allowance else None
    return {
        "service": connect.name,
        "about": connect.about,
        "has_client": connections.has_client_credentials(plugin),
        "connected": token is not None,
        "account": token.account_title if token else None,
        "needs_reconnect": bool(token and token.refresh_error),
        "reconnect_reason": token.refresh_error if token else None,
        "allowance": allowance,
        "resets_in": quota_service.describe_reset(provider=plugin.id) if allowance else "",
    }


@router.get("/connect/{plugin_id}")
def connect_start(request: Request, plugin_id: str) -> Response:
    """Send the browser to the plugin's service to ask for consent."""
    plugin = connections.connecting(plugin_id)
    if plugin is None or plugin.connect is None:
        return redirect("/settings", err="That plugin has nothing to sign in to.")
    client_id, client_secret = connections.client_credentials(plugin)
    if not (client_id and client_secret):
        return redirect(
            f"/settings#plugin-{plugin.id}",
            err=f"{plugin.title} has no OAuth client yet. The admin sets one on its card "
            "under Admin → Plugins.",
        )

    state = secrets.token_urlsafe(24)
    _states[state] = (plugin.id, dt.datetime.now(dt.timezone.utc).timestamp())
    url = oauth.build_authorization_url(plugin.connect, client_id, CONFIG.redirect_uri, state)
    if is_htmx(request):
        # An XHR cannot follow a redirect to another origin, so hand the URL
        # back and let htmx navigate the whole window to it.
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


@router.get("/oauth/callback")
def connect_callback(
    request: Request, code: str = "", state: str = "", error: str = ""
) -> RedirectResponse:
    """Where a service sends the browser back: keep the grant for this account."""
    # The browser comes back with its session cookie, which says whose grant it is.
    owner = owner_of(request)
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    issued = _states.pop(state, None)
    # Drop anything stale so the dict cannot grow without bound.
    for key, (_, at) in list(_states.items()):
        if now - at > STATE_SECONDS:
            _states.pop(key, None)
    if issued is None or now - issued[1] > STATE_SECONDS:
        return redirect("/settings", err="That sign-in link expired. Try connecting again.")

    plugin = connections.connecting(issued[0])
    if plugin is None or plugin.connect is None:
        return redirect("/settings", err="The plugin that sign-in was for is no longer here.")
    back = f"/settings#plugin-{plugin.id}"
    service = plugin.connect.name
    if error:
        explanations = {
            "access_denied": (
                f"{service} refused the request. Either you declined it, or this account is not "
                "yet allowed to use the OAuth client — some services keep a list of test users "
                "while an app is in testing."
            ),
            "redirect_uri_mismatch": (
                f"The OAuth client has no redirect URI matching {CONFIG.redirect_uri} — add it "
                "exactly, including the scheme and port."
            ),
        }
        return redirect(back, err=explanations.get(error, f"{service} returned an error: {error}"))
    if not code:
        return redirect(back, err=f"{service} did not return an authorization code.")

    with session_scope() as session, outgoing.client() as http:
        client_id, client_secret = connections.client_credentials(plugin)
        try:
            token = oauth.exchange_code(
                plugin.connect,
                code=code,
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=CONFIG.redirect_uri,
                client=http,
            )
        except oauth.OAuthError as exc:
            return redirect(back, err=f"Could not complete sign-in: {exc}")

        connections.store_token(session, token, plugin_id=plugin.id, owner=owner)
        # What the account is called, where the plugin can say: only the one
        # that publishes answers `whoami`.
        publishing = publishing_plugin()
        if publishing is not None and publishing.id == plugin.id:
            try:
                account = connections.build_client(session, http, owner).account_name()
            except PublishError:
                account = None
            if account:
                connections.store_token(
                    session, token, plugin_id=plugin.id, account_title=account, owner=owner
                )
    return redirect(back, ok=f"{service} account connected.")


@router.post("/connect/{plugin_id}/disconnect")
def connect_disconnect(request: Request, plugin_id: str) -> RedirectResponse:
    """Revoke and forget this account's sign-in to one plugin's service."""
    plugin = connections.connecting(plugin_id)
    if plugin is None or plugin.connect is None:
        return redirect("/settings", err="That plugin has nothing to sign out of.")
    with session_scope() as session, outgoing.client() as http:
        connections.disconnect(session, http, owner_of(request), plugin)
    return redirect(f"/settings#plugin-{plugin.id}", ok=f"{plugin.connect.name} account disconnected.")
