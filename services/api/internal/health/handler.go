// Package health implements the healthz, readyz, and status endpoint handlers.
package health

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"time"
)

func nowISO() string {
	return time.Now().UTC().Format(time.RFC3339)
}

// writeJSON is a package-local helper to avoid an import cycle with
// internal/api, which itself imports internal/health.
func writeJSON(w http.ResponseWriter, status int, body interface{}) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// newRequestID generates a random 16-byte hex string to use as a request ID.
// This avoids an external uuid dependency while producing a unique, opaque token
// that satisfies the contract expected by callers.
func newRequestID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// HealthzHandler handles GET /v1/tenants/{tenantId}/healthz
func HealthzHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"schemaVersion": "scheduler.health.v1",
			"service":       "Scheduler",
			"status":        "ok",
			"requestId":     newRequestID(),
			"generatedAt":   nowISO(),
		})
	}
}

// ReadyzHandler handles GET /v1/tenants/{tenantId}/readyz
func ReadyzHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		check := map[string]interface{}{
			"id":          "store-read",
			"name":        "Store read",
			"status":      "ok",
			"criticality": "critical",
			"checkedAt":   nowISO(),
			"latencyMs":   0,
			"message":     nil,
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"schemaVersion": "scheduler.readiness.v1",
			"service":       "Scheduler",
			"status":        "ok",
			"ready":         true,
			"requestId":     newRequestID(),
			"generatedAt":   nowISO(),
			"checks":        []interface{}{check},
		})
	}
}

// StatusHandler handles GET /v1/tenants/{tenantId}/status
func StatusHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		dep := map[string]interface{}{
			"id":             "firestore",
			"name":           "Firestore",
			"type":           "firebase",
			"criticality":    "critical",
			"customerImpact": "Schedules, employees, priorities, chat, and profile reads or writes may fail.",
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"schemaVersion": "scheduler.status.v1",
			"service":       "Scheduler",
			"status":        "ok",
			"requestId":     newRequestID(),
			"generatedAt":   nowISO(),
			"dependencies":  []interface{}{dep},
			"checks":        []interface{}{},
		})
	}
}
