"""Signing in, and what each kind of account may reach.

Authentication is off unless an admin is configured, so these build their own
config rather than relying on the one the other tests use.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fakes import use_config
from pamphlets.services import accounts
from pamphlets.web import guard

# The same pair as .env, so what the tests exercise is what you can sign in
# with by hand. Short on purpose: it is also what proves Pamphlets accepts an
# environment password the length rule would refuse from a form.
ADMIN = ("admin", "admin")


@pytest.fixture
def secured(db, monkeypatch):
    """An instance with an admin configured, and a member alongside."""
    from pamphlets import config, scheduler
    from pamphlets.services import accounts as accounts_module
    from pamphlets.web import app as web_app

    secured_config = config.Config(
        **{**config.CONFIG.__dict__, "admin_user": ADMIN[0], "admin_password": ADMIN[1]}
    )
    use_config(monkeypatch, secured_config)

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)

    with db.session_scope() as session:
        accounts.ensure_admin(session)
        accounts.create_user(session, "sam", "member-password")

    with TestClient(web_app.app) as client:
        yield client


def sign_in(client, username, password):
    return client.post(
        "/login", data={"username": username, "password": password}, follow_redirects=False
    )


# -- passwords -------------------------------------------------------------


def test_a_password_is_never_stored_as_itself(db):
    stored = accounts.hash_password("correct horse battery")

    assert "correct horse battery" not in stored
    assert stored.startswith("scrypt$")
    assert accounts.verify_password("correct horse battery", stored)
    assert not accounts.verify_password("Correct horse battery", stored)


def test_two_accounts_with_one_password_hash_differently(db):
    """Per-password salt: a rainbow table cannot cover both at once."""
    first = accounts.hash_password("the same password")
    second = accounts.hash_password("the same password")

    assert first != second
    assert accounts.verify_password("the same password", first)
    assert accounts.verify_password("the same password", second)


@pytest.mark.parametrize("stored", ["", "not-a-hash", "scrypt$only-two", "md5$aa$bb"])
def test_a_hash_it_cannot_read_is_a_refusal_not_a_crash(stored):
    assert accounts.verify_password("anything", stored) is False


def test_a_password_has_to_be_long_enough(db):
    with pytest.raises(accounts.AccountError):
        accounts.hash_password("short")


def test_the_same_answer_whichever_half_was_wrong(db):
    """Which of the two was wrong is not a stranger's business."""
    def refusal(username: str, password: str) -> str:
        with pytest.raises(accounts.AccountError) as raised:
            accounts.authenticate(session, username, password)
        return str(raised.value)

    with db.session_scope() as session:
        accounts.create_user(session, "sam", "member-password")

        assert refusal("nobody", "member-password") == refusal("sam", "not-the-password")


# -- sessions --------------------------------------------------------------


def test_the_cookie_is_the_secret_not_the_row(db):
    """Only a hash is stored: a copy of this table cannot sign in as anyone."""
    from pamphlets.models import LoginSession

    with db.session_scope() as session:
        user = accounts.create_user(session, "sam", "member-password")
        token = accounts.start_session(session, user)

    with db.session_scope() as session:
        stored = session.query(LoginSession).one()
        assert token not in stored.token_hash
        assert len(stored.token_hash) == 64        # sha-256, hex
        assert accounts.identify(session, token) is not None
        assert accounts.identify(session, "made-up") is None


def test_a_password_change_ends_the_other_sittings(db):
    with db.session_scope() as session:
        user = accounts.create_user(session, "sam", "member-password")
        token = accounts.start_session(session, user)
        accounts.set_password(session, user, "a-brand-new-password")

        assert accounts.identify(session, token) is None


def test_switching_an_account_off_signs_it_out(db):
    with db.session_scope() as session:
        user = accounts.create_user(session, "sam", "member-password")
        token = accounts.start_session(session, user)
        accounts.set_enabled(session, user, enabled=False)

        assert accounts.identify(session, token) is None


def test_an_expired_session_is_not_an_identity(db):
    import datetime as dt

    from pamphlets.models import LoginSession, utcnow

    with db.session_scope() as session:
        user = accounts.create_user(session, "sam", "member-password")
        token = accounts.start_session(session, user)
        session.query(LoginSession).one().expires_at = utcnow() - dt.timedelta(seconds=1)

    with db.session_scope() as session:
        assert accounts.identify(session, token) is None


# -- the admin comes from the environment ----------------------------------


def test_the_admin_is_made_from_the_environment(secured, db):
    with db.session_scope() as session:
        admin = accounts.find(session, ADMIN[0])
        assert admin is not None and admin.is_admin and admin.enabled


def test_the_environment_wins_back_a_changed_admin_password(secured, db):
    """The way back in when the password is lost: change the variable, restart."""
    with db.session_scope() as session:
        admin = accounts.find(session, ADMIN[0])
        accounts.set_password(session, admin, "something-else-entirely")

    with db.session_scope() as session:
        accounts.ensure_admin(session)
        admin = accounts.find(session, ADMIN[0])
        assert accounts.verify_password(ADMIN[1], admin.password_hash)


def test_a_former_admin_loses_the_powers(secured, db, monkeypatch):
    """Point the variable at a different name and the old one is a member."""
    from pamphlets import config

    with db.session_scope() as session:
        use_config(monkeypatch, config.Config(**{**config.CONFIG.__dict__, "admin_user": "someone-else"}))
        accounts.ensure_admin(session)

        assert accounts.find(session, ADMIN[0]).is_admin is False
        assert accounts.find(session, "someone-else").is_admin is True


def test_the_admin_account_cannot_be_deleted(secured, db):
    with db.session_scope() as session:
        with pytest.raises(accounts.AccountError):
            accounts.delete_user(session, accounts.find(session, ADMIN[0]))


# -- who may reach what ----------------------------------------------------


def test_a_stranger_is_sent_to_sign_in(secured):
    response = secured.get("/feed", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/feed"


def test_a_stranger_reaches_what_a_browser_needs_first(secured):
    """The login page, the assets that draw it, and the health check."""
    for path in ["/login", "/static/app.css", "/healthz", "/sw.js", "/manifest.webmanifest"]:
        assert secured.get(path).status_code == 200, path


def test_an_htmx_request_is_told_where_to_go(secured):
    """A plain redirect would be followed by the XHR and the login page swapped
    into whatever panel asked for a refresh."""
    response = secured.post("/sync", headers={"HX-Request": "true"}, follow_redirects=False)

    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == "/login?next=/sync"


def test_signing_in_leaves_a_locked_down_cookie(secured):
    response = sign_in(secured, *ADMIN)
    cookie = response.headers["set-cookie"]

    assert response.status_code == 303
    assert "HttpOnly" in cookie                    # no script can read it
    assert "samesite=lax" in cookie.lower()        # nor a cross-site form post


def test_signing_in_returns_to_where_you_were_headed(secured):
    secured.get("/channels", follow_redirects=False)
    response = secured.post(
        "/login",
        data={"username": ADMIN[0], "password": ADMIN[1], "next": "/channels"},
        follow_redirects=False,
    )
    assert response.headers["location"].startswith("/channels")


@pytest.mark.parametrize("elsewhere", ["//evil.test/", "http://evil.test", "/\\evil"])
def test_it_will_not_be_talked_into_sending_you_off_site(secured, elsewhere):
    """An open redirect turns a login page into a way to send someone
    somewhere else while looking like it did not."""
    response = secured.post(
        "/login",
        data={"username": ADMIN[0], "password": ADMIN[1], "next": elsewhere},
        follow_redirects=False,
    )
    assert response.headers["location"].startswith("/?") or \
        response.headers["location"] == "/"


def test_a_member_uses_the_app(secured):
    sign_in(secured, "sam", "member-password")

    for path in ["/", "/feed", "/channels", "/videos", "/focus"]:
        assert secured.get(path).status_code == 200, path


def test_a_member_is_kept_out_of_the_admins_half(secured):
    """Which is now only the accounts page. Settings, the Google connection and
    the feeds behind them belong to whoever is signed in."""
    sign_in(secured, "sam", "member-password")

    response = secured.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    # The message rides in the query string, percent-encoded.
    assert "belongs%20to%20the%20admin" in response.headers["location"]


def test_a_member_has_settings_of_their_own(secured):
    sign_in(secured, "sam", "member-password")

    assert secured.get("/settings").status_code == 200
    assert "sam" in secured.get("/settings").text


def test_a_member_can_still_configure_feeds(secured):
    """Feed and channel editing lives under /settings/ but is day-to-day use,
    not site administration — the rule is a list, not a prefix."""
    sign_in(secured, "sam", "member-password")

    # Reached by POST, so a 405 means the guard let it through.
    assert secured.post("/settings/feeds/new", data={}).status_code != 303


def test_the_admin_tab_is_only_offered_to_the_admin(secured):
    sign_in(secured, "sam", "member-password")
    assert '/admin"' not in secured.get("/").text

    secured.post("/logout")
    sign_in(secured, *ADMIN)
    assert '/admin"' in secured.get("/").text


def test_signing_out_ends_the_session(secured):
    sign_in(secured, *ADMIN)
    assert secured.get("/feed").status_code == 200

    secured.post("/logout")
    assert secured.get("/feed", follow_redirects=False).status_code == 303


def test_every_route_is_classified(secured):
    """The rules are a list, and a new route is easy to leave off it. Anything
    the app answers must be deliberately public, a member's, or the admin's."""
    from pamphlets.web.app import app as application

    unreachable = []
    for route in application.routes:
        path = getattr(route, "path", "")
        if not path or "{" in path:
            continue
        classified = guard.is_public(path) or guard.needs_admin(path) or path.startswith(
            ("/", "/partials/")
        )
        if not classified:
            unreachable.append(path)
    assert unreachable == []

    # And the three doors that must stay shut to a stranger really are.
    for path in ["/settings", "/admin", "/videos"]:
        assert not guard.is_public(path), path


# -- the admin tab ---------------------------------------------------------


def test_the_admin_can_add_an_account(secured, db):
    sign_in(secured, *ADMIN)

    secured.post("/admin/accounts", data={"username": "Kit", "password": "another-password"})

    with db.session_scope() as session:
        made = accounts.find(session, "kit")
        assert made is not None and made.enabled and not made.is_admin
    # And it can sign in.
    secured.post("/logout")
    assert sign_in(secured, "kit", "another-password").status_code == 303


def test_a_name_already_taken_is_refused(secured):
    sign_in(secured, *ADMIN)

    response = secured.post(
        "/admin/accounts", data={"username": "sam", "password": "yet-another-one"},
        follow_redirects=False,
    )
    # urlencode uses + for spaces; the middleware's quote() uses %20.
    assert "already+an+account" in response.headers["location"]


def test_a_short_password_is_refused(secured, db):
    sign_in(secured, *ADMIN)

    secured.post("/admin/accounts", data={"username": "kit", "password": "short"})

    with db.session_scope() as session:
        assert accounts.find(session, "kit") is None


def test_the_admin_can_switch_an_account_off_and_on(secured, db):
    sign_in(secured, *ADMIN)
    with db.session_scope() as session:
        sam = accounts.find(session, "sam").id

    secured.post(f"/admin/accounts/{sam}/enabled")
    with db.session_scope() as session:
        assert accounts.find(session, "sam").enabled is False

    secured.post(f"/admin/accounts/{sam}/enabled")
    with db.session_scope() as session:
        assert accounts.find(session, "sam").enabled is True


def test_the_admin_cannot_switch_itself_off(secured, db):
    """There would be no way back in short of the database."""
    sign_in(secured, *ADMIN)
    with db.session_scope() as session:
        admin_pk = accounts.find(session, ADMIN[0]).id

    secured.post(f"/admin/accounts/{admin_pk}/enabled")

    with db.session_scope() as session:
        assert accounts.find(session, ADMIN[0]).enabled is True


def test_the_admins_password_is_not_changed_from_the_page(secured, db):
    """It comes from the environment, and would be reset on the next start."""
    sign_in(secured, *ADMIN)
    with db.session_scope() as session:
        admin_pk = accounts.find(session, ADMIN[0]).id

    response = secured.post(
        f"/admin/accounts/{admin_pk}/password",
        data={"password": "changed-by-hand"}, follow_redirects=False,
    )

    assert "PAMPHLETS_ADMIN_PASSWORD" in response.headers["location"]
    with db.session_scope() as session:
        assert accounts.verify_password(ADMIN[1], accounts.find(session, ADMIN[0]).password_hash)


def test_the_admin_can_sign_someone_out_everywhere(secured, db):
    sign_in(secured, *ADMIN)
    with db.session_scope() as session:
        sam = accounts.find(session, "sam")
        token = accounts.start_session(session, sam)
        sam_pk = sam.id

    secured.post(f"/admin/accounts/{sam_pk}/sessions")

    with db.session_scope() as session:
        assert accounts.identify(session, token) is None


def test_the_admin_page_lists_the_accounts(secured):
    sign_in(secured, *ADMIN)
    body = secured.get("/admin/accounts").text

    assert "sam" in body and ADMIN[0] in body
    assert "pill-admin" in body          # and says which one is the admin


def test_the_admin_page_explains_itself_when_accounts_are_off(client):
    """Reachable by address with no admin configured, where an empty list of
    accounts would explain nothing."""
    body = client.get("/admin/accounts").text

    assert "Accounts are switched off" in body
    assert "PAMPHLETS_ADMIN_USER" in body
    assert "Add an account" not in body


@pytest.fixture
def client(db, monkeypatch):
    """The ordinary instance: no admin configured, so no sign-in."""
    from pamphlets import scheduler
    from pamphlets.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with TestClient(web_app.app) as test_client:
        yield test_client


def test_with_no_admin_the_app_is_open_and_says_so(client):
    """Upgrading an existing instance must not lock its owner out — but an
    open instance should never be mistaken for a closed one."""
    assert client.get("/feed").status_code == 200
    assert "No sign-in required" in client.get("/").text


# -- a throwaway admin password --------------------------------------------


def test_the_environment_may_set_a_password_a_form_could_not(secured, db):
    """admin/admin is how you try this out. Refusing it would mean refusing to
    start, so it is allowed — the environment is the operator's own decision,
    not a stranger's."""
    assert len(ADMIN[1]) < accounts.MIN_PASSWORD_LENGTH

    with db.session_scope() as session:
        admin = accounts.find(session, ADMIN[0])
        assert accounts.verify_password(ADMIN[1], admin.password_hash)
    assert sign_in(secured, *ADMIN).status_code == 303


def test_nobody_else_gets_that_latitude(secured, db):
    """The rule still applies to every account created through the app."""
    sign_in(secured, *ADMIN)
    secured.post("/admin/accounts", data={"username": "kit", "password": "admin"})

    with db.session_scope() as session:
        assert accounts.find(session, "kit") is None


def test_a_short_admin_password_says_so_on_the_page(secured, monkeypatch):
    """In the log at boot, and here for as long as it stands — but only to the
    admin, since nobody else can do anything about it."""
    sign_in(secured, *ADMIN)
    assert "The admin password is a short one" in secured.get("/").text

    secured.post("/logout")
    sign_in(secured, "sam", "member-password")
    assert "The admin password is a short one" not in secured.get("/").text


def test_a_long_admin_password_is_not_nagged_about(db, monkeypatch):
    from pamphlets import config

    strong = config.Config(
        **{**config.CONFIG.__dict__, "admin_user": "admin",
           "admin_password": "a-properly-long-one"}
    )
    assert strong.admin_password_weak is False
    assert config.Config(
        **{**config.CONFIG.__dict__, "admin_user": "", "admin_password": ""}
    ).admin_password_weak is False


# -- the reported failure --------------------------------------------------


def test_the_login_page_knows_you_are_already_signed_in(secured):
    """The bug behind "I can't login".

    /login is public, and the guard used to skip identifying anyone on a
    public path — so the login page never knew a session existed and offered
    the form again. Signing in appeared to do nothing.
    """
    sign_in(secured, *ADMIN)

    response = secured.get("/login", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_signing_in_is_a_navigation_not_a_swap(secured):
    """The other half of it. Boosted, htmx sends the form as an XHR; the XHR
    follows the redirect itself and htmx pushes the form's own address — so
    the browser sits at /login showing the dashboard, and shows the form again
    on reload."""
    # The login form, not the first form on the page — the top bar's sync
    # control comes before it.
    body = secured.get("/login").text
    form = body.split('action="/login"', 1)[1].split(">", 1)[0]

    assert 'hx-boost="false"' in form


def test_signing_out_is_a_navigation_too(secured):
    """It lives on the settings page now, behind the account icon."""
    sign_in(secured, *ADMIN)
    body = secured.get("/settings").text
    form = body.split('action="/logout"', 1)[1].split(">", 1)[0]

    assert 'hx-boost="false"' in form


def test_a_signed_in_visitor_is_recognised_on_public_pages(secured):
    """Which is what lets the page offer a way out rather than a way in."""
    sign_in(secured, *ADMIN)

    # The account icon is the sign of it, and the way to your own settings.
    assert 'class="account-icon"' in secured.get("/offline").text


def test_assets_do_not_cost_a_lookup_each(secured, monkeypatch):
    """Identifying on public paths must not mean identifying on every file the
    page pulls in."""
    from pamphlets.web import app as web_app

    looked = []
    original = web_app._identify
    monkeypatch.setattr(web_app, "_identify", lambda token: looked.append(token) or original(token))

    sign_in(secured, *ADMIN)
    looked.clear()
    secured.get("/static/app.css")

    assert looked == []


# -- the account icon ------------------------------------------------------


def test_the_bar_carries_an_icon_rather_than_a_name_and_a_button(secured):
    """A name and a Sign out button took the width of two controls in a bar
    that has little to spare. One letter says who, and leads to your own
    settings, where signing out lives."""
    sign_in(secured, *ADMIN)
    body = secured.get("/").text

    assert 'class="account-icon" href="/settings"' in body
    assert 'class="signed-in"' not in body          # the old pair is gone
    assert "/logout" not in body                    # it moved to settings


def test_the_icon_says_whose_it_is(secured):
    sign_in(secured, *ADMIN)
    icon = secured.get("/").text.split('class="account-icon"', 1)[1].split("</a>", 1)[0]

    assert "Signed in as admin" in icon             # on hover
    assert ">A</span>" in icon                      # and at a glance


def test_two_accounts_get_different_colours(db):
    """Picked from the name, so it never moves and nothing has to be stored."""
    first = accounts.Identity(username="admin", is_admin=True)
    second = accounts.Identity(username="sam", is_admin=False)

    assert first.hue != second.hue
    assert accounts.Identity(username="admin", is_admin=True).hue == first.hue
    assert 0 <= first.hue < 360


def test_there_is_no_icon_when_nobody_is_signed_in(client):
    assert 'class="account-icon"' not in client.get("/").text


def test_the_settings_page_is_where_you_sign_out(secured):
    sign_in(secured, *ADMIN)
    body = secured.get("/settings").text

    assert 'action="/logout"' in body
    assert "Sign out" in body
    assert "admin" in body.split("account-panel", 1)[1][:400]


def test_the_account_icon_is_square(secured):
    """It collapsed to the width of the letter: `.avatar-letter` only gets a
    size from `.channel-avatar .avatar-letter`, and this is not one of those,
    so it had none of its own."""
    import re

    css = secured.get("/static/app.css").text
    letter = re.search(r"\.account-icon \.avatar-letter\{([^}]*)\}", css)
    assert letter is not None
    assert "width:100%" in letter.group(1) and "height:100%" in letter.group(1)

    # More than one rule names the icon — one orders it in the bar, another
    # sizes it — so look at all of them for the one that holds it square.
    boxes = [m.group(1) for m in re.finditer(r"(?:^|[,}])\.account-icon\{([^}]*)\}", css)]
    assert any("aspect-ratio:1" in rule for rule in boxes), boxes


def test_the_icon_is_rounded_the_way_the_rest_of_the_app_is(secured):
    """The same corner the channel avatars wear in a heading, so a person and
    a channel look like they belong to the same app."""
    import re

    css = secured.get("/static/app.css").text
    letter = re.search(r"\.account-icon \.avatar-letter\{([^}]*)\}", css).group(1)
    channel = re.search(r"\.titled \.channel-avatar img,\.titled \.channel-avatar \.avatar-letter\{([^}]*)\}", css)

    assert "border-radius:var(--radius-md)" in letter
    assert channel is not None and "border-radius:var(--radius-md)" in channel.group(1)


def test_the_open_instance_switch_is_not_offered_when_sign_in_is_on(secured):
    """A control that does nothing, with a note saying it does nothing, is
    worse than no control."""
    sign_in(secured, *ADMIN)
    body = secured.get("/settings").text

    assert "no sign-in required" not in body
    assert 'name="hide_open_notice" value="1"' not in body or 'type="hidden"' in body






# -- the two backups -------------------------------------------------------


def test_the_site_backup_is_the_admins_alone(secured):
    """It holds every account's credentials, so it is not a member's to take."""
    sign_in(secured, "sam", "member-password")

    response = secured.post("/admin/backup", data={"passphrase": "a-long-enough-one"},
                            follow_redirects=False)
    assert response.status_code == 303
    assert "belongs%20to%20the%20admin" in response.headers["location"]


def test_the_admin_can_take_one(secured):
    import json

    sign_in(secured, *ADMIN)
    response = secured.post("/admin/backup", data={"passphrase": "a-long-enough-one"})

    assert response.status_code == 200
    assert "pamphlets-site-" in response.headers["content-disposition"]
    envelope = json.loads(response.text)
    assert envelope["format"] == "pamphlets-site-backup"
    assert "payload" in envelope and "admin" not in response.text


def test_a_weak_passphrase_is_refused_before_anything_is_written(secured):
    sign_in(secured, *ADMIN)
    response = secured.post("/admin/backup", data={"passphrase": "short"},
                            follow_redirects=False)

    assert response.status_code == 303
    assert "characters" in response.headers["location"]


def test_the_per_account_backup_is_still_everyones(secured):
    """Each account's own setup, in the clear, with no credentials in it."""
    import json

    sign_in(secured, "sam", "member-password")
    response = secured.get("/settings/backup")

    assert response.status_code == 200
    export = json.loads(response.text)
    assert "feeds" in export and "channels" in export
    assert "client_secret" not in response.text
    assert "password_hash" not in response.text


def test_accounts_have_a_page_of_their_own_under_admin(secured):
    """Like plugins: the Admin page says how many and points at the page."""
    sign_in(secured, *ADMIN)
    admin = secured.get("/admin").text
    assert 'href="/admin/accounts"' in admin and "Add an account" not in admin

    done = secured.post("/admin/accounts", data={"username": "newbie", "password": "a-long-password"},
                        follow_redirects=False)
    assert done.headers["location"].startswith("/admin/accounts?")
