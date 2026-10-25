"""A Lua piece under a Transform box: a transformation written by hand.

What comes into the Transform — data, or items read as rows — is handed to
the Lua as `data`, and the values of the Activation whose flow it is in as
`params`; whatever it `return`s is what the Transform gives out, as JSON:

    local out = {}
    for _, row in ipairs(data) do
      if (row.views or 0) > 1000 then
        out[#out + 1] = { title = row.title, views = row.views }
      end
    end
    return out

It runs in the same sandbox a plugin does (plugins/runtime): no files, no
network, nothing of the machine, and stopped if it loops or eats memory. It
is given `string`, `table` and `math`, and `json` to read or write JSON text.
What goes wrong is said in words, and the Transform gives out nothing.
"""

from __future__ import annotations

import json
from typing import Any

from ...models import GraphNode
from ...plugins.runtime import PluginError, load
from ...plugins.runtime.values import to_lua
from .errors import GraphError

#: How long a piece of Lua may be.
MOST_CODE = 20000

#: What a new Lua piece starts with: what comes in, unchanged.
STARTER = """-- `data` is what comes in: a list of rows, or one value.
-- `params` are the values its flow was activated with.
-- Whatever this returns is what the Transform gives out.
return data
"""


def code_of(node: GraphNode) -> str:
    return node.code if node.code is not None else STARTER


def save(node: GraphNode, code: str) -> None:
    """Keep a Lua piece's code, refused if Lua cannot read it."""
    if node.kind != "lua":
        raise GraphError("Only a Lua piece holds Lua.")
    code = code[:MOST_CODE]
    try:
        load("check", f"return function(data, params, json)\n{code}\nend")
    except PluginError as exc:
        raise GraphError(f"That is not Lua this can read: {str(exc).split(': ', 1)[-1]}") from exc
    node.code = code


def _json_for(lua: Any) -> Any:
    """`json.decode(text)` and `json.encode(value)`, as a table of the Lua's
    own: the sandbox lets Lua call what it is handed, never read attributes
    off a Python object."""
    from ...plugins.runtime.values import to_python

    def decode(text: object) -> Any:
        try:
            return to_lua(lua, json.loads(str(text)))
        except ValueError:
            return None

    def encode(value: object) -> str:
        return json.dumps(to_python(value), default=str)

    made = lua.table()
    made["decode"] = decode
    made["encode"] = encode
    return made


def run(code: str, data: Any, params: dict[str, str]) -> Any:
    """Run a piece's Lua over `data`, and answer what it returns, as JSON.
    Raises `GraphError`, in words, when the Lua fails."""
    wrapped = f"return function(data, params, json)\n{code}\nend"
    holder: dict[str, Any] = {}

    def world(lua: Any) -> dict[str, object]:
        holder["lua"] = lua
        return {}

    try:
        box, made = load("lua", wrapped, given=world)
        lua = holder["lua"]
        answer = box.call(made, to_lua(lua, data), to_lua(lua, dict(params)), _json_for(lua))
    except PluginError as exc:
        raise GraphError(f"The Lua failed: {str(exc).split(': ', 1)[-1]}") from exc
    try:
        # Kept to what JSON can say, which is what goes down a data wire.
        return json.loads(json.dumps(answer, default=str))
    except (TypeError, ValueError) as exc:  # pragma: no cover - to_python gives plain values
        raise GraphError(f"The Lua gave back something that is not data: {exc}") from exc
