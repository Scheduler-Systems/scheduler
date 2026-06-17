# ---- Stage 1: builder -------------------------------------------------------
# Use a pinned Go version on Alpine for a minimal, reproducible build image.
FROM golang:1.22-alpine3.19 AS builder

# Install ca-certificates so the final binary can make TLS connections.
RUN apk add --no-cache ca-certificates

WORKDIR /src

# Copy dependency manifests first to exploit Docker layer caching.
# The go.sum must be present; CI enforces it is committed.
COPY go.mod go.sum ./
RUN go mod download

# Copy the full source tree and compile.
COPY . .

# Build a statically linked binary with no debug info and no CGO dependency.
# -trimpath removes local filesystem paths from stack traces (security hardening).
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -trimpath -ldflags="-s -w" \
    -o /out/scheduler-api ./cmd/scheduler-api/...

# ---- Stage 2: runtime -------------------------------------------------------
# Use a minimal scratch-like base; distroless/static is non-root by default
# and contains only the CA bundle and TZ data — nothing else.
FROM gcr.io/distroless/static-debian12:nonroot

# Copy the compiled binary from the builder stage.
COPY --from=builder /out/scheduler-api /scheduler-api

# Port the service listens on (overridable via $PORT environment variable).
EXPOSE 8080

# Run as the built-in non-root user provided by distroless/static:nonroot.
# UID 65532 is the "nonroot" user in this image.
USER nonroot:nonroot

ENTRYPOINT ["/scheduler-api"]
