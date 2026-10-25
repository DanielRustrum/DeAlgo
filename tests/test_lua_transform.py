"""Transformations written in Lua: a Lua piece under a Transform box, and a
plugin's own transformation slotted there the same way."""

from __future__ import annotations

import pytest

from pamphlets.models import GraphNode
from pamphlets.plugins import registry
from pamphlets.services import graph
from pamphlets.services.graph import activations, scripting
from tests.test_graph import build, canvas  # noqa: F401


def _transform_of(session, data_rows):
    """A Transform box with an Activation's values wired in as its data."""
    target = graph.add_trigger(session, trigger_kind="activation")
    activations.set_params(target, list(data_rows), [""] * len(data_rows))
    box = graph.add_transform(session, label="Shape")
    graph.connect(session, target, box)
    return target, box


def test_lua_changes_what_a_transform_gives_out(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        target, box = _transform_of(session, ["city"])
        activations.set_off(target, {"city": "tucson"})
        piece = graph.add_piece(session, kind="lua", host=box)
        assert scripting.code_of(piece) == scripting.STARTER
        assert graph.formatting.transformed(session, box, None) == [{"city": "tucson"}]
        scripting.save(piece, """
            local out = {}
            for _, row in ipairs(data) do
              out[#out + 1] = { place = string.upper(row.city), from_params = params.city,
                                text = json.encode({ n = 1 }) }
            end
            return out
        """)
        assert graph.formatting.transformed(session, box, None) == [
            {"place": "TUCSON", "from_params": "tucson", "text": '{"n": 1}'}
        ]
        assert graph.piece_note(piece, box).startswith("Lua · ")


def test_lua_that_fails_says_why_and_gives_out_nothing(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        _, box = _transform_of(session, ["city"])
        piece = graph.add_piece(session, kind="lua", host=box)
        with pytest.raises(graph.GraphError, match="not Lua"):
            scripting.save(piece, "return ((")
        scripting.save(piece, "return data[1].nothing.deeper")
        assert graph.formatting.transformed(session, box, None) is None
        assert "The Lua failed" in graph.formatting.transform_error(session, box, None)
        # Kept in its sandbox: nothing of the machine, and stopped if it loops.
        scripting.save(piece, "return os.getenv('HOME')")
        assert graph.formatting.transformed(session, box, None) is None
        scripting.save(piece, "while true do end")
        assert "too long" in graph.formatting.transform_error(session, box, None)


def test_the_canvas_saves_a_lua_piece(canvas, db):
    with db.session_scope() as session:
        box = graph.add_transform(session, label="Shape")
        box_pk = box.id
    made = canvas.post("/graph/nodes", data={"kind": "lua", "attach_to": str(box_pk), "x": "0", "y": "0"}).json()
    piece = next(n for n in made["nodes"] if n["kind"] == "lua")
    assert piece["code"] == scripting.STARTER
    refused = canvas.post(f"/graph/nodes/{piece['id']}", data={"label": "", "lua_code": "return (("})
    assert refused.status_code == 400
    saved = canvas.post(f"/graph/nodes/{piece['id']}", data={"label": "", "lua_code": "return { n = 2 }"}).json()
    assert next(n for n in saved["nodes"] if n["id"] == piece["id"])["code"] == "return { n = 2 }"
    with db.session_scope() as session:
        assert session.get(GraphNode, piece["id"]).attached_to == box_pk


@pytest.fixture
def here(tmp_path, monkeypatch):
    folder = tmp_path / "plugins"
    folder.mkdir()
    monkeypatch.setattr(registry.storage, "folder", lambda: folder)
    registry.reload()
    yield folder
    registry.reload()


def test_a_plugin_may_offer_a_transformation(here, db):
    (here / "doubler.lua").write_text("""
        return { api = 1, name = "Doubler", augmentations = { {
          kind = "double", label = "Double", under = "transform",
          fields = { { name = "by", label = "By", default = "2" } },
          transform = function(data, settings, params)
            local out = {}
            for i, row in ipairs(data) do out[i] = { city = row.city, times = tonumber(settings.by) } end
            return out
          end,
        } } }
    """, encoding="utf-8")
    registry.reload()
    assert registry.current().augmentation("doubler:double").under == "transform"
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        target, box = _transform_of(session, ["city"])
        activations.set_off(target, {"city": "Mesa"})
        graph.add_piece(session, kind=graph.RULE, ref="doubler:double", host=box, settings={"by": "3"})
        assert graph.formatting.transformed(session, box, None) == [{"city": "Mesa", "times": 3}]
