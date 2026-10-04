# Running in Production

## Rules that matter

- **Run exactly one instance.** One SQLite file and an in-process scheduler: a second copy would
  write everything twice and fight over locks. The compose file pins `replicas: 1` and stops the
  old container before starting a new one.
- **Set `DEALGO_PUBLIC_URL` to the public address** (e.g. `https://dealgo.example.com`) and register
  `<that>/oauth/callback` with Google. De-Algo builds the redirect from this, not from the request.
- **Use a subdomain, not a subpath.** Pages and assets are served from `/`.
- **Keep `/data` on local disk.** SQLite over network filesystems corrupts.
- **Use HTTPS** if you want the [installable app and offline reading](Installing%20as%20an%20App.md).

## Behind a reverse proxy

De-Algo trusts `X-Forwarded-*` headers, so TLS can end at the proxy.

The cluster overlay drops the published port and joins an existing `proxy` network with Traefik
labels:

```bash
make up CLUSTER=1
# or: docker compose -f docker-compose.yml -f compose.cluster.yml up -d
```

Edit the labels in `compose.cluster.yml` for your proxy. Needs Compose 2.24+; on older versions,
skip the overlay and set `DEALGO_BIND=127.0.0.1:8080` instead.

## Portainer

`stack.yml` is a self-contained stack using a prebuilt image.

1. **Stacks → Add stack**, then paste `stack.yml` or point at this repository.
2. Set at least `DEALGO_IMAGE`, `DEALGO_PUBLIC_URL` and the admin variables.
3. Deploy. Enable **Automatic updates** to follow new images.

## A release image

Every version tag has a page under the repository's **Releases**, with the image attached as a
file for each platform (`amd64`, `arm64`) and a `SHA256SUMS.txt`. No build is needed:

```bash
curl -LO <release page>/download/v0.2.0/dealgo-v0.2.0-amd64.tar.gz
curl -LO <release page>/download/v0.2.0/SHA256SUMS.txt
sha256sum --check --ignore-missing SHA256SUMS.txt
gunzip -c dealgo-v0.2.0-amd64.tar.gz | docker load      # gives dealgo:0.2.0
```

Then set `DEALGO_IMAGE=dealgo:0.2.0` and start it. Each release's notes have the exact links.

### Building one yourself

`make release` builds the checkout into `releases/<version>/`, using the version in
`pyproject.toml`. It writes the same image file and `SHA256SUMS.txt` that a release carries, plus
a README with the load command. No tag, forge or buildx setup is needed.

- It builds for your machine's own platform; `make release PLATFORMS=linux/amd64,linux/arm64`
  builds both, which needs emulation for the other one.
- It won't overwrite a version it has already built; bump the version, or pass `FORCE=1`.

### Publishing it to Docker Hub and other registries

`make push-release` takes `releases/<version>/`, checks its files against their checksums, and
pushes the image to every *hub* listed in `ops/hubs.toml`.

- **The hubs file:** each `[[hub]]` block gives a registry, a repository and the tags to push
  (`{version}` and `latest` by default). Add a block to publish somewhere else; delete it, or set
  `enabled = false`, to stop. The Docker Hub entry needs its `repository` filled in (like
  `yourname/dealgo`) before it will push.
- **Signing in:** either run `docker login` for each registry once beforehand, or set the
  environment variables a hub names (for Docker Hub, `DOCKERHUB_USERNAME`, and `DOCKERHUB_TOKEN`
  holding an access token). The token goes to Docker on standard input and is never printed.
- **Options:**
  - `make push-release DRY_RUN=1` prints every command without running any.
  - `HUB=docker-hub` sends to that hub only, even a disabled one.
  - `VERSION=0.1.0` publishes an older build than the one in the code.

A release with several platforms is pushed once per platform, then joined under each tag, so
`docker pull` picks the right one on any machine.

## Pushing the image to a registry

```bash
make publish                     # build and push for this machine's architecture
make publish-multiarch           # amd64 + arm64 (needs buildx)
make publish TAG=v0.2.0          # a release tag
```

## Container hardening

The container runs as uid 10001 with a read-only root filesystem, no capabilities and
`no-new-privileges`. `/data` is the only writable path. If you bind-mount a host folder, run
`chown 10001:10001` on it first.

**Related:** [Environment Variables](Environment%20Variables.md) · [Accounts](Accounts.md)
