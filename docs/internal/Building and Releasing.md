# Building and Releasing

## Local development

```bash
python -m venv .venv && .venv/bin/pip install -e . pytest mypy libsass
npm install                  # TypeScript, for editing scripts
make dev                     # rebuild assets, run on :8080 with ./data, reading .env
```

| Target | Does |
| --- | --- |
| `make css` / `make js` / `make assets` | Compile SCSS and TS into `web/static` (commit the output); `make js` also joins scripts written as parts |
| `make watch-css` / `make watch-js` | Rebuild on save |
| `make test` / `make typecheck` | Suite / mypy + tsc |
| `make docs` | Generate API reference into `docs/internal/autodoc` |
| `make toc` | Rebuild the docs' tables of contents |

## The image — `Dockerfile`

`python:3.12-slim`; dependencies installed first for layer caching; the package installed with
`pip install .` (so `package-data` globs decide what ships); runs as UID 10001; `/data` volume;
health check hits `/healthz` on `DEALGO_PORT`. Entry `dealgo serve`.

No Node and no Sass compiler in the image: compiled assets are committed.

## Compose

`docker-compose.yml` runs one service with a read-only root filesystem, `/data` on a named volume
(`dealgo_dealgo-data`), and the environment documented in the wiki. `compose.cluster.yml` drops the
published port and joins a shared reverse-proxy network (`make … CLUSTER=1`).

| Target | Does |
| --- | --- |
| `make build` / `make up` | Build; start and wait for healthy |
| `make logs` / `make shell` / `make restart` / `make down` | Operate |
| `make publish` / `make publish-multiarch` | Push to `$(REGISTRY)/rusty/dealgo` |
| `make release-image RELEASE=vX.Y.Z` | Build the release files into `build/release`, as CI does |
| `make clean` | Delete the data volume (asks first) |

## Releases — `.gitea/workflows/release.yml`

On a pushed tag `v*`, or by hand with a tag name:

1. **test** — `ops/publish_release.py check` (the tag must equal `version` in `pyproject.toml`
   and `__version__` in `dealgo/__init__.py`), then Python 3.12, `mypy`, Node 22, `tsc` (pages,
   worker, parts), `pytest -q`.
2. **release** — `ops/publish_release.py build` exports the image with buildx for `linux/amd64`
   and `linux/arm64` (arm64 under QEMU, so slowly) as `dealgo-<tag>-<arch>.tar.gz`, plus
   `SHA256SUMS.txt`; `publish` creates the tag's release on the Releases page, if missing, and
   attaches the files, replacing any of the same name. A tag with a suffix (`v1.2.0-rc.1`) is a
   pre-release.

The image is not pushed to a registry; whoever installs it downloads a file and runs
`gunzip -c dealgo-<tag>-amd64.tar.gz | docker load`, which gives `dealgo:<version>`. The release
notes say so, with the links.

The token: the secret `RELEASE_TOKEN` (an access token with `write:repository`), else the job's
own token. A reverse proxy in front of Forgejo must accept uploads of about 80 MB.
`RELEASE_PLATFORMS=linux/amd64` narrows a local build.

GitHub Actions syntax, except the release API calls, which are Forgejo's.

## The wiki — `.gitea/workflows/wiki.yml`

On a push to `main` that touches `docs/wiki/`, or by hand, `ops/publish_wiki.py publish` makes the
repository's Forgejo wiki a copy of `docs/wiki`:

- A Forgejo wiki is one flat folder of pages named with dashes, and pages in subfolders are not
  served, so the tree is flattened: `README.md` → `Home`, `Nodes/Filter.md` → `Nodes-Filter`, a
  folder's `README.md` or `GETTING STARTED.md` → the folder's name.
- Every link between pages is rewritten to its new page; a link to any other file in the repository
  becomes a link to that file. A sidebar (the home page's index) and a footer are added.
- The wiki's whole content is replaced, so edits made in the wiki itself are lost on the next
  publish — the footer says where to edit.
- A push cannot create a wiki that has never had a page, so the script adds one through the API
  first when needed.

The token: the secret `WIKI_TOKEN` (an access token with `write:repository`), else the job's own
token. `make wiki` builds the pages into `build/wiki` to look at before pushing.

## Releasing

1. `make assets && make test && make typecheck`.
2. Bump `__version__` in `dealgo/__init__.py` and `version` in `pyproject.toml`.
3. Commit, tag `vX.Y.Z` and push the tag (`git push origin vX.Y.Z`); CI tests, builds and
   attaches the image to the release.

## Packaging pitfall

Anything the app reads from its own package must match `[tool.setuptools.package-data]` in
`pyproject.toml`. Globs are not recursive unless written `**`. A test checks every such path.
