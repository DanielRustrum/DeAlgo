"""Publishing the wiki: links between pages become page names, and a link to
any other file in the repository becomes the forge's address for it — its
raw file, for an image, so the image is shown."""

from __future__ import annotations

from ops import publish_wiki as wiki

BLOB = "https://forge.example/owner/repo/src/branch/main"


def test_pages_files_and_images_are_each_linked_their_own_way():
    page = wiki.WIKI / "Focus Mode.md"
    text = (
        "See [the feed](The%20Feed%20Page.md#the-shelf), [the plugin](../../ops/README.md) and\n"
        "![Focus mode](images/focus.png)\n"
        "```\n![in code](images/focus.png)\n```\n"
    )
    made = wiki.rewrite(text, page, BLOB)
    assert "[the feed](The-Feed-Page#the-shelf)" in made
    assert f"[the plugin]({BLOB}/ops/README.md)" in made
    assert "![Focus mode](https://forge.example/owner/repo/raw/branch/main/docs/wiki/images/focus.png)" in made
    assert "![in code](images/focus.png)" in made
