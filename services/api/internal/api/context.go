package api

// context.go re-exports the context accessors from httputil so that callers
// that already import "api" don't need an additional import.
// The canonical definitions live in internal/httputil to break the import
// cycle: api/router → schedules/schedgy/health → api.

import (
	"context"

	"github.com/Scheduler-Systems/scheduler-api/internal/httputil"
)

// WithActor wraps httputil.WithActor.
func WithActor(ctx context.Context, actor httputil.Actor) context.Context {
	return httputil.WithActor(ctx, actor)
}

// ActorFromContext wraps httputil.ActorFromContext.
func ActorFromContext(ctx context.Context) httputil.Actor {
	return httputil.ActorFromContext(ctx)
}

// WithParams wraps httputil.WithParams.
func WithParams(ctx context.Context, params map[string]string) context.Context {
	return httputil.WithParams(ctx, params)
}

// ParamsFromContext wraps httputil.ParamsFromContext.
func ParamsFromContext(ctx context.Context) map[string]string {
	return httputil.ParamsFromContext(ctx)
}
