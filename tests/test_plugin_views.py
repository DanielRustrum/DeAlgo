"""A plugin's own layout for its items in Focus mode: XML made into HTML from
a fixed set of components, CSS kept to the view and scoped to it, and a form
in it sent back to the plugin."""

from __future__ import annotations

import pytest

from pamphlets.models import Channel, Video, utcnow
from pamphlets.plugins import registry
from pamphlets.services.plugin_views import render_xml, scope_css, shown
from tests.test_graph import canvas  # noqa: F401


def test_only_the_components_survive_and_addresses_are_web_ones():
    made = render_xml(
        '<view><heading level="1">Hi</heading><text class="note x" onclick="steal()">words</text>'
        '<link href="javascript:alert(1)">bad</link><image src="data:text/html,x" alt="a"/>'
        "<script>alert(1)</script><iframe src='https://evil.example'/>"
        '<input name="r" type="file"/></view>'
    )
    assert '<h2 class="pv-heading">Hi</h2>' in made
    assert 'class="pv-text note x"' in made and "onclick" not in made
    assert "javascript:" not in made and "data:text" not in made
    assert "<script" not in made and "<iframe" not in made
    assert 'type="text"' in made  # a file input is not one a view may have


def test_xml_that_could_expand_or_cannot_be_read_is_refused():
    with pytest.raises(ValueError, match="DOCTYPE"):
        render_xml('<!DOCTYPE x [<!ENTITY a "aaaa">]><view>&a;</view>')
    assert shown("p", "<view><unclosed></view>", "").error.startswith("the view is not readable XML")


def test_css_is_scoped_to_the_view_and_kept_to_styling_it():
    css = scope_css(
        "@import url(https://x.example/a.css); heading, .x:hover { color: red; background: url(javascript:x) }"
        " body { margin: 0 } @font-face { src: url(https://x.example/f.woff) }"
        " @media (max-width: 600px) { row { display: block } } </style><script>",
        ".s",
    )
    assert ".s .pv-heading, .s .x:hover { color: red }" in css
    assert "@media (max-width: 600px) { .s .pv-row { display: block } }" in css
    assert "@import" not in css and "font-face" not in css and "javascript" not in css and "</" not in css


@pytest.fixture
def here(tmp_path, monkeypatch):
    folder = tmp_path / "plugins"
    folder.mkdir()
    monkeypatch.setattr(registry.storage, "folder", lambda: folder)
    registry.reload()
    yield folder
    registry.reload()


PLUGIN = """
return { api = 1, id = "cards", name = "Cards", sources = { {
  kind = "cards", label = "Cards", example = "anything",
  recognise = function(ref) return nil end,
  style = "heading { color: rebeccapurple } .votes { font-weight: bold }",
  view = function(item, settings)
    return '<view><heading level="1">' .. item.title .. '</heading>'
      .. '<text class="votes">0 votes</text>'
      .. '<form><input name="vote" type="number"/><button>Vote</button></form></view>'
  end,
  act = function(item, values, settings)
    return '<view><text class="votes">' .. values.vote .. ' votes for ' .. item.title .. '</text></view>'
  end,
} } }
"""


def test_a_plugin_lays_its_items_out_and_answers_its_forms(here, canvas, db):
    (here / "cards.lua").write_text(PLUGIN, encoding="utf-8")
    registry.reload()
    assert registry.current().has_view("cards")
    with db.session_scope() as session:
        channel = Channel(channel_id="deck", title="Deck", source_kind="cards")
        session.add(channel)
        session.flush()
        item = Video(video_id="c1", channel_pk=channel.id, title="First card", kind="post", published_at=utcnow())
        session.add(item)
        session.flush()
        item_pk = item.id

    shown_now = canvas.get(f"/focus/item/{item_pk}/view").json()
    assert '<h2 class="pv-heading">First card</h2>' in shown_now["html"]
    assert 'data-pv-form' in shown_now["html"]
    assert shown_now["css"].startswith('.pv-root[data-pv="cards"] .pv-heading { color: rebeccapurple }')

    answered = canvas.post(f"/focus/item/{item_pk}/view", data={"vote": "3"}).json()
    assert "3 votes for First card" in answered["html"]


QUEUE_READER = """
return { api = 1, id = "inbox", name = "Inbox",
  permissions = { { name = "read", why = "To show what was sent." } },
  sources = { {
    kind = "inbox", label = "Inbox", example = "anything",
    recognise = function(ref) return nil end,
    view = function(item, settings)
      local sent = pamphlets.queue("feedback")
      local out = '<view><list>'
      for _, row in ipairs(sent) do out = out .. '<item>' .. row.name .. '</item>' end
      return out .. '</list></view>'
    end,
} } }
"""


def test_a_plugin_with_read_permission_reads_a_form_queue(here, canvas, db):
    from pamphlets.services.graph import forms

    (here / "inbox.lua").write_text(QUEUE_READER, encoding="utf-8")
    registry.reload()
    with db.session_scope() as session:
        channel = Channel(channel_id="box", title="Box", source_kind="inbox")
        session.add(channel)
        session.flush()
        item = Video(video_id="i1", channel_pk=channel.id, title="Mail", kind="post", published_at=utcnow())
        session.add(item)
        from pamphlets.models import FormSubmission

        session.add(FormSubmission(queue="feedback", fields='{"name": "Ada"}'))
        session.flush()
        item_pk = item.id
    # Not granted read: it sees nothing.
    assert "<li" not in canvas.get(f"/focus/item/{item_pk}/view").json()["html"]
    registry.set_granted("inbox", frozenset({"read"}))
    registry.reload()
    assert '<li class="pv-item">Ada</li>' in canvas.get(f"/focus/item/{item_pk}/view").json()["html"]
