.PHONY: setup dev api build start check test docker-up docker-down docker-logs docker-status docker-import-data
export PATH := $(CURDIR)/.tools/node/bin:$(PATH)
setup:
	uv sync --locked
	cd frontend && npm ci
api:
	uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
dev:
	python3 scripts/dev.py
build:
	cd frontend && npm run build
start: build api
check:
	uv run ruff check app scripts tests
	uv run ruff format --check app scripts tests
	cd frontend && npm run check && npm run test && npm run build
test:
	uv run pytest
docker-up:
	docker compose up -d --build --wait
docker-down:
	docker compose down
docker-logs:
	docker compose logs -f --tail=100 app
docker-status:
	docker compose ps
docker-import-data:
	python3 scripts/import_docker_data.py
