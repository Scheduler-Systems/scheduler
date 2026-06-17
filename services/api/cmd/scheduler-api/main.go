// Package main is the entrypoint for the scheduler-api HTTP server.
//
// It reads $PORT (defaulting to 8080) and starts the server with:
//   - An in-memory store (NewMemoryStore)
//   - A per-tenant rate limiter (100 req/min by default)
//   - The root HTTP handler wired up by api.NewHandler
package main

import (
	"log"
	"net/http"
	"os"
	"time"

	"github.com/Scheduler-Systems/scheduler-api/internal/api"
	"github.com/Scheduler-Systems/scheduler-api/internal/auth"
	"github.com/Scheduler-Systems/scheduler-api/internal/store"
)

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	st := store.NewMemoryStore()

	// 100 requests per tenant per minute matches the production intent.
	// Adjust via environment variable in a future iteration if needed.
	rl := api.NewRateLimiter(100)

	// The actor's identity and role are derived ONLY from the verified Firebase
	// ID token (issue #19), never from client headers. Default project matches
	// the .claude firebase rule (your-firebase-project-id); override via env.
	projectID := firstNonEmpty(
		os.Getenv("FIREBASE_PROJECT_ID"),
		os.Getenv("GCLOUD_PROJECT"),
		"your-firebase-project-id",
	)

	var verifier auth.Verifier
	if os.Getenv("FIREBASE_AUTH_EMULATOR_HOST") != "" {
		// Dev-local only: the Auth emulator issues unsigned tokens. This path is
		// gated strictly behind the emulator host env var so it can never run in
		// production.
		log.Printf("scheduler-api: using Firebase Auth EMULATOR verifier (project %s) — DEV ONLY", projectID)
		verifier = auth.NewEmulatorVerifier(projectID)
	} else {
		verifier = auth.NewFirebaseVerifier(projectID)
	}

	handler := api.NewHandler(st, rl, verifier)

	addr := ":" + port
	log.Printf("scheduler-api listening on %s", addr)

	srv := &http.Server{
		Addr:              addr,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("server error: %v", err)
	}
}

// firstNonEmpty returns the first non-empty string from the arguments.
func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}
