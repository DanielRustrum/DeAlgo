"""Following a newsletter by where it lives.

A newsletter is a publication you know by name — platformer.news, not
platformer.news/feed. Substack, Ghost, beehiiv, Buttondown and WordPress all
publish a feed and all put it somewhere slightly different, so the app asks
the site rather than making somebody find out which of those theirs runs on.

Two halves, and they are tested apart because only one of them is allowed to
make a request: working out that what was typed is a *place*, and then asking
that place where its feed is.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from tests.test_graph import canvas  # noqa: F401

from dealgo import sources
from dealgo.sources import newsletter

FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Platformer</title>
  <item><title>One</title><link>https://platformer.news/one</link></item>
</channel></rss>"""

PAGE = """<!doctype html><html><head>
  <title>Platformer</title>
  <link rel="stylesheet" href="/style.css">
  <link rel="alternate" type="application/rss+xml" title="Platformer" href="/hidden/feed.xml">
</head><body>Words.</body></html>"""


class Server:
    """Whatever addresses are set up, and nothing else.

    Records what was asked for, in order, because the order is half of what
    this is for: the site's own answer before a guess, and no guessing at all
    once something has answered.
    """

    def __init__(
        self, pages: dict[str, httpx.Response], lands: dict[str, str] | None = None
    ):
        self.pages = pages
        #: Where a request ends up, for the addresses that redirect. The
        #: client follows them, so what comes back says where it came from.
        self.lands = lands or {}
        self.asked: list[str] = []

    def get(self, url, headers=None):
        self.asked.append(url)
        landed = self.lands.get(url, url)
        answer = self.pages.get(landed) or httpx.Response(404, text="not here")
        return httpx.Response(
            answer.status_code, text=answer.text,
            headers=dict(answer.headers),
            request=httpx.Request("GET", landed, headers=headers),
        )


def html(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "text/html"})


def xml(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "application/rss+xml"})


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Rate limiting is somebody else's test, and it keeps state per host."""
    from dealgo.sources import patience

    monkeypatch.setattr(patience, "hold", lambda url: None)
    monkeypatch.setattr(patience, "note", lambda response: None)


# -- what was typed --------------------------------------------------------


@pytest.mark.parametrize(
    "typed, site",
    [
        ("platformer.news", "https://platformer.news/"),
        ("  platformer.news  ", "https://platformer.news/"),
        ("https://platformer.news", "https://platformer.news/"),
        # However deep into it you happened to be standing.
        ("https://platformer.news/archive?sort=new", "https://platformer.news/"),
        # One spelling, so typing it two ways does not watch it twice.
        ("www.platformer.news", "https://platformer.news/"),
        ("HTTPS://Platformer.News/", "https://platformer.news/"),
    ],
)
def test_where_a_newsletter_lives_is_read_forgivingly(typed, site):
    assert newsletter.site_url(typed) == site


@pytest.mark.parametrize("typed", ["", "   ", "platformer", "a name with spaces", "/feed"])
def test_a_word_is_not_somewhere_a_newsletter_could_live(typed):
    """Guessing ".com" from a word would watch whatever happens to be there
    rather than what was meant."""
    assert newsletter.site_url(typed) == ""


def test_a_newsletter_box_resolves_to_a_place_with_no_feed_yet(monkeypatch):
    """Working out what a reference is never makes a request. A newsletter
    says so by resolving with no feed address at all."""
    found = sources.resolve("platformer.news", within="newsletter")

    assert found.kind == "newsletter"
    assert found.key == "https://platformer.news/"
    assert found.title == "platformer.news"
    assert found.feed_url == ""
    assert found.needs_finding is True


def test_a_word_typed_into_a_newsletter_box_is_refused_with_an_example():
    with pytest.raises(sources.UnknownSource) as refused:
        sources.resolve("platformer", within="newsletter")

    assert "platformer.news" in str(refused.value)


def test_every_other_kind_knows_where_its_feed_is_already():
    """Only a newsletter is a place rather than a feed."""
    said = sources.resolve("https://example.com/feed.xml", within="rss")

    assert said.needs_finding is False


def test_a_newsletter_is_offered_alongside_the_address_box():
    offered = {kind.name: kind for kind in sources.all_kinds()}

    assert offered["newsletter"].noun == "Newsletter"
    # Neither is a plugin's: they are what every plugin is built on.
    assert offered["newsletter"].plugin == ""
    # And it cannot go into a YouTube playlist, which only YouTube can.
    assert offered["newsletter"].playlistable is False


def test_a_newsletter_links_back_to_where_it_lives():
    """The one kind whose key is its home, because that is how it is named."""
    assert sources.home_url("newsletter", "https://platformer.news/") == (
        "https://platformer.news/"
    )


# -- asking the site -------------------------------------------------------


def test_the_feed_a_site_declares_is_the_one_taken():
    """Its own answer beats a guess at it, and costs one request to get."""
    server = Server({
        "https://platformer.news/": html(PAGE),
        "https://platformer.news/hidden/feed.xml": xml(FEED),
    })

    found = newsletter.find("https://platformer.news/", server)

    assert found.feed_url == "https://platformer.news/hidden/feed.xml"
    assert found.title == "Platformer"
    # The page, then the feed it named. Nothing was guessed at.
    assert server.asked == [
        "https://platformer.news/",
        "https://platformer.news/hidden/feed.xml",
    ]


def test_a_site_that_declares_nothing_is_looked_for_in_the_usual_places():
    server = Server({
        "https://ghost.example/": html("<html><head></head><body>Hi</body></html>"),
        "https://ghost.example/rss": xml(FEED),
    })

    found = newsletter.find("https://ghost.example/", server)

    assert found.feed_url == "https://ghost.example/rss"
    # In order, and it stopped at the one that answered.
    assert server.asked == [
        "https://ghost.example/",
        "https://ghost.example/feed",
        "https://ghost.example/rss",
    ]


def test_a_site_that_will_not_give_up_its_page_is_still_looked_for():
    """Plenty refuse a bare GET and serve a feed happily."""
    server = Server({"https://shy.example/feed": xml(FEED)})

    found = newsletter.find("https://shy.example/", server)

    assert found.feed_url == "https://shy.example/feed"


def test_a_page_of_html_at_feed_is_not_a_feed():
    """Plenty of sites answer 200 to anything, so each address is confirmed
    by being parsed rather than by its status."""
    server = Server({
        "https://vague.example/": html("<html><head></head></html>"),
        "https://vague.example/feed": html("<html>not a feed</html>"),
        "https://vague.example/rss": html("<html>nor this</html>"),
        "https://vague.example/feed.xml": xml(FEED),
    })

    found = newsletter.find("https://vague.example/", server)

    assert found.feed_url == "https://vague.example/feed.xml"


def test_the_other_of_www_and_the_bare_domain_is_tried_too():
    """A Substack answers at the bare domain, declares a /feed that is not
    there, and serves the real one only on www. Which is not unusual enough
    to leave somebody to work out for themselves."""
    server = Server({
        "https://acx.example/": html(
            '<html><head><link rel="alternate" type="application/rss+xml" '
            'href="https://acx.example/feed"></head></html>'
        ),
        "https://www.acx.example/feed": xml(FEED),
    })

    found = newsletter.find("https://acx.example/", server)

    assert found.feed_url == "https://www.acx.example/feed"
    # Its own answer first, then the usual places, then the other host. Two
    # things are being guessed at once by then, so it comes last.
    assert server.asked.index("https://acx.example/feed") < server.asked.index(
        "https://www.acx.example/feed"
    )


def test_a_site_that_moved_is_asked_where_it_landed():
    """What a page declares is relative to where it answered, not to what was
    typed into the box. A relative href on a site that redirects to www would
    otherwise be read against the address nobody ended up at."""
    server = Server(
        pages={
            "https://www.plat.example/": html(
                '<html><head><link rel="alternate" '
                'type="application/rss+xml" href="/rss/"></head></html>'
            ),
            "https://www.plat.example/rss/": xml(FEED),
        },
        lands={"https://plat.example/": "https://www.plat.example/"},
    )

    found = newsletter.find("https://plat.example/", server)

    assert found.feed_url == "https://www.plat.example/rss/"


def test_a_site_with_no_feed_says_so_rather_than_failing():
    """An ordinary answer to give somebody who has just typed a name."""
    server = Server({"https://quiet.example/": html("<html><head></head></html>")})

    assert newsletter.find("https://quiet.example/", server) is None


def test_it_stops_asking_somebody_elses_server_after_a_while():
    """Each address is a request. A site that has not answered by the sixth
    is not hiding its feed, it has not got one."""
    server = Server({"https://quiet.example/": html("<html><head></head></html>")})

    newsletter.find("https://quiet.example/", server)

    # The page, and then no more than the usual places are worth trying.
    assert len(server.asked) <= 1 + newsletter.MOST_TRIED


def test_a_declaration_below_the_head_is_not_the_page_saying_what_it_publishes():
    said = newsletter.declared(
        '<html><head><link rel="alternate" type="application/rss+xml" href="/real">'
        '</head><body><link rel="alternate" type="application/rss+xml" href="/no">'
        "</body></html>",
        "https://a.example/",
    )

    assert said == ["https://a.example/real"]


def test_a_stylesheet_is_not_a_feed():
    said = newsletter.declared(
        '<html><head><link rel="stylesheet" href="/style.css">'
        '<link rel="alternate" type="text/html" href="/print">'
        "</head></html>",
        "https://a.example/",
    )

    assert said == []


# -- from the canvas -------------------------------------------------------


def test_a_newsletter_box_finds_the_feed_and_starts_watching(db, monkeypatch):
    """The whole of it: drag out a Newsletter box, type where it lives, and
    the app works out where its feed is."""
    from dealgo.models import Channel
    from dealgo.services import channels as channel_service

    server = Server({
        "https://platformer.news/": html(PAGE),
        "https://platformer.news/hidden/feed.xml": xml(FEED),
    })

    with db.session_scope() as session:
        made = channel_service.add_source(
            session, "platformer.news", server, within="newsletter"
        )
        assert made.source_kind == "newsletter"
        # Named by where it lives, and called what the feed calls itself.
        assert made.channel_id == "https://platformer.news/"
        assert made.source_url == "https://platformer.news/hidden/feed.xml"
        assert made.title == "Platformer"

    with db.session_scope() as session:
        assert session.scalars(select(Channel)).one().title == "Platformer"


def test_a_site_with_no_feed_is_refused_with_somewhere_to_go(db):
    """Rather than a channel that would sit there failing every sync."""
    from dealgo.services import channels as channel_service

    server = Server({"https://quiet.example/": html("<html><head></head></html>")})

    with db.session_scope() as session:
        with pytest.raises(channel_service.ChannelError) as refused:
            channel_service.add_source(
                session, "quiet.example", server, within="newsletter"
            )

    assert "does not publish a feed" in str(refused.value)
    assert "Feed address" in str(refused.value)


def test_the_same_newsletter_typed_twice_is_one_channel(db):
    from dealgo.services import channels as channel_service

    server = Server({
        "https://platformer.news/": html(PAGE),
        "https://platformer.news/hidden/feed.xml": xml(FEED),
    })

    with db.session_scope() as session:
        channel_service.add_source(session, "platformer.news", server, within="newsletter")
        with pytest.raises(channel_service.ChannelError) as again:
            # A different spelling of the same place.
            channel_service.add_source(
                session, "https://www.platformer.news/archive", server,
                within="newsletter",
            )

    assert "already being watched" in str(again.value)


def test_the_palette_offers_a_newsletter_beside_the_address_box(canvas):
    body = canvas.get("/channels").text

    assert 'data-source-kind="newsletter"' in body
    assert 'data-source-kind="rss"' in body
    # Both at the top level: neither is filed under Plugins, because neither
    # is one.
    top = body.split('<details class="palette-group">', 1)[0]
    assert 'data-source-kind="newsletter"' in top


def test_an_empty_newsletter_box_says_what_to_type(canvas):
    made = canvas.post(
        "/graph/nodes", data={"kind": "source", "source_kind": "newsletter"}
    ).json()
    box = [node for node in made["nodes"] if node.get("asks")][0]

    assert box["asks"]["label"] == "Newsletter"
    assert "platformer.news" in box["asks"]["example"]
    assert box["asks"]["known"] is True
