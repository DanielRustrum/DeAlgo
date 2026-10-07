# Pamphlets container tasks. Run `make` for the list.

# make <target> CLUSTER=1 adds the reverse-proxy overlay.
CLUSTER   ?=
COMPOSE_FILES := $(if $(CLUSTER),-f docker-compose.yml -f compose.cluster.yml,)
COMPOSE   ?= docker compose $(COMPOSE_FILES)
SERVICE   ?= pamphlets
REGISTRY  ?= repo.home.app
IMAGE     ?= $(REGISTRY)/rusty/pamphlets
TAG       ?= latest
URL     ?= http://localhost:8080
PY      ?= .venv/bin/python

.DEFAULT_GOAL := help
.PHONY: help config publish publish-multiarch backup build up down restart logs ps shell sync add channels watched remove-watched info test typecheck css js assets watch-css watch-js fonts docs toc wiki release-image release push-release dev clean

help: ## Show this help
	@echo "Pamphlets — usage: make <target>"
	@echo
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[1m%-15s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  make add CHANNEL=@handle       watch a channel"
	@echo "  make watched VIDEO=<id|url>    mark videos watched"

build: ## Build the image
	$(COMPOSE) build

publish: ## Build and push the image to the registry (IMAGE=, TAG=)
	docker build -t $(IMAGE):$(TAG) .
	docker push $(IMAGE):$(TAG)
	@echo
	@echo "Pushed $(IMAGE):$(TAG) — Portainer can pull it with PAMPHLETS_IMAGE=$(IMAGE):$(TAG)"

publish-multiarch: ## Build and push for amd64 and arm64 (needs buildx)
	docker buildx build --platform linux/amd64,linux/arm64 -t $(IMAGE):$(TAG) --push .

config: ## Show the resolved compose configuration
	$(COMPOSE) config

up: ## Start Pamphlets in the background and wait for it to be healthy (CLUSTER=1 for the proxy overlay)
	$(COMPOSE) up -d
	@printf 'waiting for %s ' "$(URL)"; \
	for _ in $$(seq 1 60); do \
		state=$$($(COMPOSE) ps -q $(SERVICE) | xargs -r docker inspect -f '{{.State.Health.Status}}' 2>/dev/null); \
		if [ "$$state" = healthy ]; then printf '\n\nPamphlets is running at %s\n' "$(URL)"; exit 0; fi; \
		if [ "$$state" = unhealthy ]; then printf '\n\nContainer is unhealthy. Try: make logs\n'; exit 1; fi; \
		printf '.'; sleep 1; \
	done; \
	printf '\n\nStill not healthy. Try: make logs\n'; exit 1

down: ## Stop Pamphlets, keeping its data
	$(COMPOSE) down

restart: ## Restart the container
	$(COMPOSE) restart $(SERVICE)

logs: ## Follow the logs
	$(COMPOSE) logs -f $(SERVICE)

ps: ## Show container state
	$(COMPOSE) ps

shell: ## Open a shell in the running container
	$(COMPOSE) exec $(SERVICE) sh

sync: ## Run one sync pass and exit (FORCE=1 ignores channel minimums)
	$(COMPOSE) run --rm $(SERVICE) sync $(if $(FORCE),--force,)

add: ## Watch a source (CHANNEL=@handle, a URL, a UC… id, r/name, or a feed address)
	@test -n "$(CHANNEL)" || { echo "usage: make add CHANNEL=@handle"; exit 2; }
	$(COMPOSE) run --rm $(SERVICE) add "$(CHANNEL)"

backup: ## Write a JSON backup of the setup to ./pamphlets-backup.json
	$(COMPOSE) run --rm -T $(SERVICE) export > pamphlets-backup.json
	@echo "wrote pamphlets-backup.json"

channels: ## List watched channels
	$(COMPOSE) run --rm $(SERVICE) channels

watched: ## Mark videos watched (VIDEO="id-or-url ...")
	@test -n "$(VIDEO)" || { echo 'usage: make watched VIDEO="dQw4w9WgXcQ"'; exit 2; }
	$(COMPOSE) run --rm $(SERVICE) watched $(VIDEO)

remove-watched: ## Remove watched videos from the playlist
	$(COMPOSE) run --rm $(SERVICE) remove-watched

info: ## Show Pamphlets's configuration
	$(COMPOSE) run --rm $(SERVICE) status

test: ## Run the test suite locally
	$(PY) -m pytest

typecheck: ## Check the types, both languages (mypy --strict, tsc --noEmit)
	$(PY) -m mypy
	npx tsc --noEmit
	npx tsc -p tsconfig.sw.json --noEmit
	npx tsc -p tsconfig.parts.json --noEmit

css: ## Compile web/styles with Tailwind into the stylesheet the app serves (needs npm install)
	$(PY) ops/build_css.py

fonts: ## Copy the typefaces from node_modules into static/fonts (needs npm install)
	$(PY) ops/vendor_fonts.py

js: ## Compile web/ts into the scripts the app serves
	npx tsc
	npx tsc -p tsconfig.sw.json
	@# The canvas and Focus mode are folders of parts, compiled apart and joined.
	npx tsc -p tsconfig.parts.json
	$(PY) ops/join_scripts.py

watch-js: ## Recompile the page scripts on save (the worker and the scripts written as parts need `make js`)
	npx tsc --watch

assets: fonts css js ## Rebuild the fonts, the stylesheet and the scripts

watch-css: ## Recompile the stylesheet on every save to web/styles or a template (run `make css` before committing)
	npx tailwindcss --input pamphlets/web/styles/app.css --output pamphlets/web/static/app.css --watch

AUTODOC := docs/internal/autodoc

docs: ## Generate the API reference from code comments into docs/internal/autodoc
	@# Importing pamphlets.config creates its data folder, so point it somewhere disposable.
	@tmp=$$(mktemp -d); \
	PAMPHLETS_DATA_DIR=$$tmp PAMPHLETS_DATABASE_URL=sqlite:// \
		$(PY) -m pdoc pamphlets --docformat markdown --no-show-source -o $(AUTODOC)/python; \
	status=$$?; rm -rf $$tmp; exit $$status
	npm install --prefix $(AUTODOC) --no-audit --no-fund
	cd $(AUTODOC) && npx typedoc --options typedoc.browser.json --logLevel Warn
	cd $(AUTODOC) && npx typedoc --options typedoc.worker.json --logLevel Warn
	@echo "open index.html in $(AUTODOC)/python, browser and service-worker"

toc: ## Rebuild the Table of Contents in docs/wiki and docs/internal
	$(PY) ops/build_toc.py

wiki: ## Build the Forgejo wiki pages from docs/wiki into build/wiki, to preview (CI publishes them)
	@rm -rf build/wiki
	$(PY) ops/publish_wiki.py build build/wiki

release-image: ## Build the release image files into build/release, as CI does (RELEASE=vX.Y.Z)
	@test -n "$(RELEASE)" || { echo "usage: make release-image RELEASE=v1.2.3"; exit 1; }
	@rm -rf build/release
	$(PY) ops/publish_release.py build $(RELEASE) build/release

release: ## Build the image into releases/<version>/ locally (PLATFORMS=linux/amd64,linux/arm64, FORCE=1)
	$(if $(PLATFORMS),RELEASE_PLATFORMS=$(PLATFORMS)) FORCE=$(FORCE) $(PY) ops/publish_release.py local releases

push-release: ## Publish releases/<version>/ to the hubs in ops/hubs.toml (HUB=name,name VERSION=x.y.z DRY_RUN=1)
	$(PY) ops/publish_image.py $(if $(VERSION),--version $(VERSION)) $(if $(HUB),--hub $(HUB)) $(if $(DRY_RUN),--dry-run)

dev: assets ## Run the app locally without Docker (reads .env if there is one)
	@set -a; [ -f .env ] && . ./.env; set +a; $(PY) -m pamphlets serve

clean: ## Stop Pamphlets and delete its data volume (irreversible)
	@printf 'This erases every watched channel and all sync history. Type yes to confirm: '; \
	read answer; [ "$$answer" = yes ] || { echo "aborted"; exit 1; }
	$(COMPOSE) down -v
