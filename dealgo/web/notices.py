"""What plugins have to say to the person in front of the page, as toasts.

A plugin that signs people in to its service says, in its `connect.notices`,
what it wants said while that is not done: not signed in, signed in but asked
to again, or the admin has not given it an OAuth client. The plugin chooses
the words; the host decides which applies, where it links to, and that it is
a standing toast — one that stays until dealt with or dismissed for the
session — rather than a banner in the middle of a page.
"""

from __future__ import annotations

from typing import Any

from ..db import session_scope
from ..services import connections
from ..services.scope import OwnerId


def plugin_notices(owner: OwnerId, is_admin: bool) -> list[dict[str, Any]]:
    """Each plugin's toast for this account right now, if it has one to show."""
    out: list[dict[str, Any]] = []
    plugins = [
        plugin for plugin in connections.every_connecting()
        if plugin.connect is not None and plugin.connect.notices
    ]
    if not plugins:
        return out
    with session_scope() as session:
        for plugin in plugins:
            connect = plugin.connect
            assert connect is not None
            said = dict(connect.notices)
            if not connections.has_client_credentials(plugin):
                state = "setup"
                # Only the admin can do anything about it, so only the admin
                # is sent anywhere.
                link = (f"/admin/plugins#plugin-{plugin.id}-setup", "Set it up in Admin →") \
                    if is_admin else None
            else:
                token = connections.get_token(session, owner, plugin.id)
                if token is None:
                    state, link = "connect", (f"/settings#plugin-{plugin.id}", "Connect in Settings →")
                elif token.refresh_error:
                    state, link = "reconnect", (f"/settings#plugin-{plugin.id}", "Reconnect in Settings →")
                else:
                    continue
            if state not in said:
                continue
            out.append({
                "key": f"plugin-{plugin.id}-{state}",
                "plugin": plugin.title,
                "text": said[state],
                "link": link,
                "bad": state == "reconnect",
            })
    return out
