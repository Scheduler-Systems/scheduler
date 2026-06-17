package api

// handler.go re-exports the JSON helpers from httputil so that callers that
// already import "api" don't need an additional import.
// The canonical definitions live in internal/httputil.

import (
	"net/http"

	"github.com/Scheduler-Systems/scheduler-api/internal/httputil"
)

// WriteJSON delegates to httputil.WriteJSON.
func WriteJSON(w http.ResponseWriter, status int, body interface{}) {
	httputil.WriteJSON(w, status, body)
}

// ReadJSON delegates to httputil.ReadJSON.
func ReadJSON(r *http.Request, dst interface{}) error {
	return httputil.ReadJSON(r, dst)
}
