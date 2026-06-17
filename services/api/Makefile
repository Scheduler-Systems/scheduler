.PHONY: run test build dev dev-node

# -------------------------------------------------------------------------
# Go targets
# -------------------------------------------------------------------------

## run: start the scheduler-api server (default port 8080, override with PORT=)
run:
	go run ./cmd/scheduler-api/...

## test: run all Go tests
test:
	go test ./...

## build: compile a production binary to ./bin/scheduler-api
build:
	mkdir -p bin
	go build -o bin/scheduler-api ./cmd/scheduler-api/...

## dev: start the Go server locally (alias of `run`; default port 8080, override with PORT=)
dev:
	go run ./cmd/scheduler-api/...

# -------------------------------------------------------------------------
# Legacy Node.js target (kept for backward-compat during migration)
# -------------------------------------------------------------------------

## dev-node: start the legacy Node.js dev server
dev-node:
	npm run dev
