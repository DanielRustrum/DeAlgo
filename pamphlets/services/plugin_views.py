"""A plugin's own layout for one of its items in Focus mode: XML and CSS.

A source plugin may say how its items look when opened in Focus mode, with
a `view` function answering XML made of the components below, and a `style`
of CSS to dress them. Neither is trusted: the XML is rebuilt as HTML from
these components only — every other tag and attribute is dropped, addresses
are kept to web ones — and the CSS is read rule by rule, kept to what styles
the view, and scoped so it reaches nothing outside it. A form in the view
is sent back to the plugin's `act`, which answers the view again.

    <view>
      <heading level="1">{title}</heading>
      <row><image src="…" alt="…"/><text class="note">{words}</text></row>
      <embed src="https://youtu.be/…"/>
      <form><input name="rating" type="range" min="1" max="5"/><button>Rate</button></form>
    </view>
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from urllib.parse import urlparse

from . import embeds

#: How long a view's XML, and its CSS, may be.
MOST_XML = 200_000
MOST_CSS = 50_000
#: How deep a view may nest.
MOST_DEPTH = 40

#: Each component: the HTML it becomes, and the attributes it keeps (beyond
#: `class` and `title`, which every one keeps).
COMPONENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "view": ("div", ()),
    "box": ("div", ()),
    "row": ("div", ()),
    "column": ("div", ()),
    "grid": ("div", ()),
    "spacer": ("div", ()),
    "heading": ("h2", ("level",)),
    "text": ("span", ()),
    "paragraph": ("p", ()),
    "p": ("p", ()),
    "strong": ("strong", ()),
    "em": ("em", ()),
    "small": ("small", ()),
    "code": ("code", ()),
    "pre": ("pre", ()),
    "quote": ("blockquote", ()),
    "badge": ("span", ()),
    "divider": ("hr", ()),
    "break": ("br", ()),
    "link": ("a", ("href",)),
    "image": ("img", ("src", "alt", "width", "height")),
    "video": ("video", ("src", "poster", "loop", "muted")),
    "audio": ("audio", ("src", "loop")),
    "embed": ("div", ("src",)),
    "list": ("ul", ("ordered",)),
    "item": ("li", ()),
    "table": ("table", ()),
    "table-row": ("tr", ()),
    "cell": ("td", ("span",)),
    "header-cell": ("th", ("span",)),
    "details": ("details", ("open",)),
    "summary": ("summary", ()),
    "progress": ("progress", ("value", "max")),
    "form": ("form", ()),
    "label": ("label", ()),
    "input": ("input", ("name", "type", "value", "placeholder", "min", "max", "step", "required", "pattern", "checked")),
    "textarea": ("textarea", ("name", "placeholder", "rows", "required")),
    "select": ("select", ("name", "required")),
    "option": ("option", ("value", "selected")),
    "button": ("button", ("href", "name", "value")),
}
#: What an `input` may be.
INPUT_TYPES = ("text", "number", "date", "email", "url", "checkbox", "radio", "range", "color", "time", "hidden")
#: Components with nothing inside them.
EMPTY = ("divider", "break", "image", "input", "embed")
CLASS = re.compile(r"[^A-Za-z0-9_ -]")


@dataclass(frozen=True)
class Shown:
    """A view as a page shows it: HTML, its scoped CSS, and what went wrong."""

    html: str
    css: str
    error: str = ""


def _web(url: str) -> str:
    """An address kept only if it is a web one."""
    url = url.strip()
    return url if urlparse(url).scheme in ("http", "https") else ""


def _attrs(tag: str, element: ElementTree.Element) -> str:
    """An element's attributes as kept: its own allowed ones, made safe."""
    _, allowed = COMPONENTS[tag]
    kept: list[str] = [f'class="pv-{tag} {CLASS.sub("", element.get("class", ""))[:200].strip()}"'.replace(" \"", "\"")]
    if element.get("title"):
        kept.append(f'title="{html.escape(element.get("title", "")[:300])}"')
    for name in allowed:
        value = element.get(name)
        if value is None or name in ("level", "ordered", "src") and tag in ("heading", "list", "embed"):
            continue
        value = value[:2000]
        if name in ("href", "src", "poster"):
            value = _web(value)
            if not value:
                continue
        if name == "type" and value not in INPUT_TYPES:
            value = "text"
        if name in ("loop", "muted", "required", "checked", "selected", "open"):
            kept.append(name)
            continue
        kept.append(f'{name}="{html.escape(value)}"')
    return " " + " ".join(kept)


def _render(element: ElementTree.Element, depth: int = 0) -> str:
    """One component and everything in it, as HTML. Unknown ones are left
    out, but what is written inside them is kept, as text."""
    tag = element.tag
    inner = html.escape(element.text or "")
    if depth < MOST_DEPTH:
        for child in element:
            inner += _render(child, depth + 1)
            inner += html.escape(child.tail or "")
    if tag not in COMPONENTS:
        return inner
    made, _ = COMPONENTS[tag]
    attrs = _attrs(tag, element)
    if tag == "heading":
        level = element.get("level", "2")
        made = f"h{min(6, max(2, int(level) + 1 if level.isdigit() else 3))}"
    if tag == "list" and element.get("ordered") in ("", "true", "yes", "1"):
        made = "ol"
    if tag == "link":
        return f'<a{attrs} target="_blank" rel="noopener noreferrer">{inner}</a>'
    if tag == "image":
        return f'<img{attrs} loading="lazy" referrerpolicy="no-referrer">'
    if tag in ("video", "audio"):
        return f"<{made}{attrs} controls preload=\"metadata\">{inner}</{made}>"
    if tag == "embed":
        found = embeds.embed_for(_web(element.get("src", "")))
        if found.kind in ("youtube", "vimeo"):
            return (f'<div{attrs}><iframe src="{html.escape(found.src)}" loading="lazy" allowfullscreen '
                    'allow="autoplay; encrypted-media; picture-in-picture; fullscreen" '
                    'referrerpolicy="strict-origin-when-cross-origin"></iframe></div>')
        if found.kind == "file":
            return f'<div{attrs}><video src="{html.escape(found.src)}" controls preload="metadata"></video></div>'
        if found.kind == "link":
            return f'<a class="pv-link" href="{html.escape(found.src)}" target="_blank" rel="noopener noreferrer">{html.escape(found.src)}</a>'
        return ""
    if tag == "button" and element.get("href"):
        href = _web(element.get("href", ""))
        return f'<a{attrs} href="{html.escape(href)}" target="_blank" rel="noopener noreferrer">{inner}</a>' if href else ""
    if tag == "button":
        return f'<button{attrs} type="submit">{inner}</button>'
    if tag == "form":
        return f'<form{attrs} data-pv-form>{inner}</form>'
    if tag in EMPTY:
        return f"<{made}{attrs}>"
    return f"<{made}{attrs}>{inner}</{made}>"


def render_xml(xml: str) -> str:
    """A view's XML as HTML, its components only. Raises `ValueError`, in
    words, for XML that cannot be read."""
    xml = (xml or "").strip()
    if not xml:
        return ""
    if len(xml) > MOST_XML:
        raise ValueError("the view is too long")
    if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ValueError("a view has no DOCTYPE or entities")
    try:
        root = ElementTree.fromstring(xml if xml.startswith("<view") else f"<view>{xml}</view>")
    except ElementTree.ParseError as exc:
        raise ValueError(f"the view is not readable XML: {exc}") from exc
    return _render(root)


# -- CSS ---------------------------------------------------------------------

#: What a declaration may not say anywhere in it.
REFUSED = re.compile(r"expression\s*\(|javascript:|behavior\s*:|-moz-binding|@import|</", re.I)
URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)
COMPONENT_NAME = re.compile(
    r"(?<![\w.#:-])(" + "|".join(sorted((re.escape(n) for n in COMPONENTS), key=len, reverse=True)) + r")(?![\w-])"
)


def _declarations(block: str) -> str:
    """A rule's declarations, each kept only if it says nothing refused and
    reaches no address but a web one."""
    kept = []
    for one in block.split(";"):
        one = one.strip()
        if not one or ":" not in one or REFUSED.search(one):
            continue
        if any(not _web(found.group(2)) and not found.group(2).startswith("data:image/") for found in URL.finditer(one)):
            continue
        kept.append(one)
    return "; ".join(kept)


def _selector(selector: str, scope: str) -> str:
    """One selector, scoped to the view, its component names made classes."""
    selector = selector.strip()
    if not selector:
        return ""
    selector = COMPONENT_NAME.sub(lambda m: f".pv-{m.group(1)}", selector)
    if selector.startswith((":root", "html", "body")):
        selector = selector.split(None, 1)[1] if " " in selector else ""
    return f"{scope} {selector}".strip() if selector else scope


def scope_css(css: str, scope: str) -> str:
    """A plugin's CSS, kept to what styles its view and scoped to it: every
    selector inside `scope`, @media and @supports kept around what they hold,
    every other at-rule dropped."""
    css = re.sub(r"/\*.*?\*/", "", (css or "")[:MOST_CSS], flags=re.S)
    # At-rules that are a statement rather than a block — @import, @charset,
    # @namespace — go first, so they cannot run into the rule after them.
    css = re.sub(r"@[a-zA-Z-]+[^{};]*;", "", css)
    out: list[str] = []
    at = 0
    while at < len(css):
        opening = css.find("{", at)
        if opening < 0:
            break
        head = css[at:opening].strip()
        # The block, braces balanced.
        depth, end = 1, opening + 1
        while end < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[end], 0)
            end += 1
        body = css[opening + 1:end - 1]
        at = end
        if head.lower().startswith(("@media", "@supports")):
            inner = scope_css(body, scope)
            if inner:
                out.append(f"{head} {{ {inner} }}")
            continue
        if head.lower().startswith("@keyframes"):
            name = re.sub(r"[^\w-]", "", head[10:])
            if name and not REFUSED.search(body):
                out.append(f"@keyframes {name} {{ {body} }}")
            continue
        if head.startswith("@"):
            continue
        selectors = ", ".join(filter(None, (_selector(one, scope) for one in head.split(","))))
        declared = _declarations(body)
        if selectors and declared:
            out.append(f"{selectors} {{ {declared} }}")
    return " ".join(out)


def shown(plugin_id: str, xml: str, css: str) -> Shown:
    """A view as a page shows it, scoped to `[data-pv="plugin_id"]`."""
    scope = f'.pv-root[data-pv="{re.sub(r"[^a-z0-9_-]", "", plugin_id)}"]'
    try:
        made = render_xml(xml)
    except ValueError as exc:
        return Shown("", "", str(exc))
    return Shown(made, scope_css(css, scope))
