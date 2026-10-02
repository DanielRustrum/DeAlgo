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
| `make clean` | Delete the data volume (asks first) |

## CI — `.gitea/workflows/publish.yml`

On push to `main`, tags `v*`, or manual dispatch:

1. **test** — Python 3.12, `mypy`, Node 22, `tsc` (pages, worker, parts), `pytest -q`.
2. **publish** — buildx for `linux/amd64` and `linux/arm64`; tags `latest` (default branch),
   short SHA, and semver from tags; push to the Gitea registry; optional Portainer webhook.

GitHub Actions syntax, so it moves to `.github/workflows/` unchanged.

## Releasing

1. `make assets && make test && make typecheck`.
2. Bump `__version__` in `dealgo/__init__.py` and `version` in `pyproject.toml`.
3. Tag `vX.Y.Z` and push; CI builds and pushes the semver tags.

## Packaging pitfall

Anything the app reads from its own package must match `[tool.setuptools.package-data]` in
`pyproject.toml`. Globs are not recursive unless written `**`. A test checks every such path.
