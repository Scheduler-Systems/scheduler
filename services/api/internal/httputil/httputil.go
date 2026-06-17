// Package httputil provides shared HTTP helpers (JSON encoding/decoding,
// context value accessors) used by handler packages and the api routing layer.
//
// It lives in its own package to break the import cycle that would otherwise
// occur if handler packages (schedules, schedgy, health) imported api, while
// api/router.go also imports those handler packages.
package httputil

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

// maxRequestBodyBytes caps inbound request bodies at 1 MB to prevent a
// slow/malicious client from exhausting server memory via io.ReadAll.
const maxRequestBodyBytes = 1 << 20 // 1 MB

// -----------------------------------------------------------------------
// JSON helpers
// -----------------------------------------------------------------------

// WriteJSON encodes body as JSON and writes it with the given status code.
// The Content-Type header is always set to application/json; charset=utf-8.
func WriteJSON(w http.ResponseWriter, status int, body interface{}) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// ReadJSON decodes the request body into dst.  GET requests return without
// reading the body (mirrors readJson in the original Node.js app.mjs).
// Bodies larger than maxRequestBodyBytes are rejected to prevent memory
// exhaustion from an unbounded io.ReadAll.
func ReadJSON(r *http.Request, dst interface{}) error {
	if r.Method == http.MethodGet {
		return nil
	}
	// Read one byte beyond the limit so we can distinguish "exactly at limit"
	// from "over limit" without a second read.
	body, err := io.ReadAll(io.LimitReader(r.Body, maxRequestBodyBytes+1))
	if err != nil {
		return err
	}
	if len(body) > maxRequestBodyBytes {
		return fmt.Errorf("request body exceeds %d bytes", maxRequestBodyBytes)
	}
	if len(body) == 0 {
		return nil
	}
	return json.Unmarshal(body, dst)
}

// -----------------------------------------------------------------------
// Context value keys and accessors
// -----------------------------------------------------------------------

type contextKey string

const (
	actorKey  contextKey = "actor"
	paramsKey contextKey = "params"
)

// Actor holds the authenticated caller context extracted from request headers.
type Actor struct {
	TenantID      string
	UserID        string
	Email         string
	Role          string
	CorrelationID string
}

// WithActor returns a new context carrying the authenticated Actor.
func WithActor(ctx context.Context, actor Actor) context.Context {
	return context.WithValue(ctx, actorKey, actor)
}

// ActorFromContext retrieves the Actor stored by WithActor.
// It panics if the actor is not present (programming error — router always sets it).
func ActorFromContext(ctx context.Context) Actor {
	return ctx.Value(actorKey).(Actor)
}

// WithParams stores route params in the context so handlers can read them.
func WithParams(ctx context.Context, params map[string]string) context.Context {
	return context.WithValue(ctx, paramsKey, params)
}

// ParamsFromContext retrieves the route params stored by WithParams.
func ParamsFromContext(ctx context.Context) map[string]string {
	v := ctx.Value(paramsKey)
	if v == nil {
		return nil
	}
	return v.(map[string]string)
}
