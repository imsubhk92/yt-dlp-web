.PHONY: setup dev api build start check test
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
