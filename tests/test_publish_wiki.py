"""Publishing the wiki: links between pages become page names, and a link to
any other file in the repository becomes the forge's address for it — its
raw file, for an image, so the image is shown."""

from __future__ import annotations

from ops import publish_wiki as wiki

BLOB = "https://forge.example/owner/repo/src/branch/main"


def test_pages_files_and_images_are_each_linked_their_own_way():
    page = wiki.WIKI / "Content View.md"
    text = (
        "See [the feed](List%20View.md#the-shelf), [the plugin](../../ops/README.md) and\n"
        "![Content view](images/content.png)\n"
        "```\n![in code](images/content.png)\n```\n"
    )
    made = wiki.rewrite(text, page, BLOB)
    assert "[the feed](List-View#the-shelf)" in made
    assert f"[the plugin]({BLOB}/ops/README.md)" in made
    assert "![Content view](https://forge.example/owner/repo/raw/branch/main/docs/wiki/images/content.png)" in made
    assert "![in code](images/content.png)" in made
