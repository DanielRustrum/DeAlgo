# Dealgo container tasks. Run `make` for the list.

# make <target> CLUSTER=1 adds the reverse-proxy overlay.
CLUSTER   ?=
COMPOSE_FILES := $(if $(CLUSTER),-f docker-compose.yml -f compose.cluster.yml,)
COMPOSE   ?= docker compose $(COMPOSE_FILES)
SERVICE   ?= dealgo
REGISTRY  ?= repo.home.app
IMAGE     ?= $(REGISTRY)/rusty/dealgo
TAG       ?= latest
URL     ?= http://localhost:8080
PY      ?= .venv/bin/python

.DEFAULT_GOAL := help
.PHONY: help config publish publish-multiarch backup build up down restart logs ps shell sync add channels watched remove-watched info test typecheck css js assets watch-css watch-js docs toc dev clean

help: ## Show this help
	@echo "Dealgo — usage: make <target>"
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
	@echo "Pushed $(IMAGE):$(TAG) — Portainer can pull it with DEALGO_IMAGE=$(IMAGE):$(TAG)"

publish-multiarch: ## Build and push for amd64 and arm64 (needs buildx)
	docker buildx build --platform linux/amd64,linux/arm64 -t $(IMAGE):$(TAG) --push .

config: ## Show the resolved compose configuration
	$(COMPOSE) config

up: ## Start Dealgo in the background and wait for it to be healthy (CLUSTER=1 for the proxy overlay)
	$(COMPOSE) up -d
	@printf 'waiting for %s ' "$(URL)"; \
	for _ in $$(seq 1 60); do \
		state=$$($(COMPOSE) ps -q $(SERVICE) | xargs -r docker inspect -f '{{.State.Health.Status}}' 2>/dev/null); \
		if [ "$$state" = healthy ]; then printf '\n\nDealgo is running at %s\n' "$(URL)"; exit 0; fi; \
		if [ "$$state" = unhealthy ]; then printf '\n\nContainer is unhealthy. Try: make logs\n'; exit 1; fi; \
		printf '.'; sleep 1; \
	done; \
	printf '\n\nStill not healthy. Try: make logs\n'; exit 1

down: ## Stop Dealgo, keeping its data
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

backup: ## Write a JSON backup of the setup to ./de-algo-backup.json
	$(COMPOSE) run --rm -T $(SERVICE) export > de-algo-backup.json
	@echo "wrote de-algo-backup.json"

channels: ## List watched channels
	$(COMPOSE) run --rm $(SERVICE) channels

watched: ## Mark videos watched (VIDEO="id-or-url ...")
	@test -n "$(VIDEO)" || { echo 'usage: make watched VIDEO="dQw4w9WgXcQ"'; exit 2; }
	$(COMPOSE) run --rm $(SERVICE) watched $(VIDEO)

remove-watched: ## Remove watched videos from the playlist
	$(COMPOSE) run --rm $(SERVICE) remove-watched

info: ## Show Dealgo's configuration
	$(COMPOSE) run --rm $(SERVICE) status

test: ## Run the test suite locally
	$(PY) -m pytest

typecheck: ## Check the types, both languages (mypy --strict, tsc --noEmit)
	$(PY) -m mypy
	npx tsc --noEmit
	npx tsc -p tsconfig.sw.json --noEmit
	npx tsc -p tsconfig.parts.json --noEmit

css: ## Compile web/scss into the stylesheet the app serves
	$(PY) -m dealgo.web.styles

js: ## Compile web/ts into the scripts the app serves
	npx tsc
	npx tsc -p tsconfig.sw.json
	@# The canvas and Focus mode are folders of parts, compiled apart and joined.
	npx tsc -p tsconfig.parts.json
	$(PY) -m dealgo.web.scripts

watch-js: ## Recompile the page scripts on save (the worker and the scripts written as parts need `make js`)
	npx tsc --watch

assets: css js ## Rebuild both the stylesheet and the scripts

watch-css: ## Recompile the stylesheet whenever a partial changes
	@command -v inotifywait >/dev/null || { echo "needs inotify-tools"; exit 2; }
	@echo "watching dealgo/web/scss — ctrl-c to stop"
	@while true; do \
		inotifywait -qq -r -e close_write dealgo/web/scss; \
		$(PY) -m dealgo.web.styles >/dev/null && echo "rebuilt $$(date +%H:%M:%S)"; \
	done

AUTODOC := docs/internal/autodoc

docs: ## Generate the API reference from code comments into docs/internal/autodoc
	@# Importing dealgo.config creates its data folder, so point it somewhere disposable.
	@tmp=$$(mktemp -d); \
	DEALGO_DATA_DIR=$$tmp DEALGO_DATABASE_URL=sqlite:// \
		$(PY) -m pdoc dealgo --docformat markdown --no-show-source -o $(AUTODOC)/python; \
	status=$$?; rm -rf $$tmp; exit $$status
	npm install --prefix $(AUTODOC) --no-audit --no-fund
	cd $(AUTODOC) && npx typedoc --options typedoc.browser.json --logLevel Warn
	cd $(AUTODOC) && npx typedoc --options typedoc.worker.json --logLevel Warn
	@echo "open index.html in $(AUTODOC)/python, browser and service-worker"

toc: ## Rebuild the Table of Contents in docs/wiki and docs/internal
	$(PY) docs/toc.py

dev: assets ## Run the app locally without Docker (reads .env if there is one)
	@set -a; [ -f .env ] && . ./.env; set +a; $(PY) -m dealgo serve

clean: ## Stop Dealgo and delete its data volume (irreversible)
	@printf 'This erases every watched channel and all sync history. Type yes to confirm: '; \
	read answer; [ "$$answer" = yes ] || { echo "aborted"; exit 1; }
	$(COMPOSE) down -v
