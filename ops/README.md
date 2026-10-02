# ops

DevOps scripts. None of them is part of the app or ships in its package; the Makefile, CI and the
tests run them.

| Script | Does | Run by |
| --- | --- | --- |
| `build_css.py` | Compiles `dealgo/web/scss/` into `dealgo/web/static/app.css` | `make css` |
| `join_scripts.py` | Joins scripts written as parts (`web/ts/graph/`, `web/ts/focus/`) into one file each, after `tsc` | `make js` |
| `build_toc.py` | Writes the Table of Contents for `docs/wiki` and `docs/internal` | `make toc` |
| `publish_wiki.py` | Builds `docs/wiki` into Forgejo wiki pages, and publishes them | `make wiki` (preview), `.gitea/workflows/wiki.yml` |
| `publish_release.py` | Builds the Docker image as files per platform, and attaches them to a tag's release | `make release-image` (build only), `.gitea/workflows/release.yml` |

Run any of them from the repository root, e.g. `.venv/bin/python ops/build_toc.py`.
