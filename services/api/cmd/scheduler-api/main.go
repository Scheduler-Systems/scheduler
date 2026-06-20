// Package main is the entrypoint for the scheduler-api HTTP server.
//
// It reads $PORT (defaulting to 8080) and starts the server with:
//   - A persistence store selected by SCHEDULER_STORE (memory | firestore)
//   - A per-tenant rate limiter (100 req/min by default)
//   - The root HTTP handler wired up by api.NewHandler
package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"strings"
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

	// The actor's identity and role are derived ONLY from the verified Firebase
	// ID token (issue #19), never from client headers. Default project matches
	// the .claude firebase rule (your-firebase-project-id); override via env.
	projectID := firstNonEmpty(
		os.Getenv("FIREBASE_PROJECT_ID"),
		os.Getenv("GCLOUD_PROJECT"),
		"your-firebase-project-id",
	)

	st := resolveStore(projectID)

	// 100 requests per tenant per minute matches the production intent.
	// Adjust via environment variable in a future iteration if needed.
	rl := api.NewRateLimiter(100)

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

// resolveStore selects the persistence backend from SCHEDULER_STORE:
//   - "" or "memory" → in-memory (default; data is lost on restart)
//   - "firestore"    → Cloud Firestore (survives restart). Uses the same
//     project as auth; targets the emulator when FIRESTORE_EMULATOR_HOST is set,
//     otherwise Application Default Credentials.
//
// A firestore selection that fails to initialise is fatal (rather than silently
// falling back to memory) so a misconfigured persistent deployment fails loud.
func resolveStore(projectID string) store.Store {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("SCHEDULER_STORE"))) {
	case "", "memory":
		log.Printf("scheduler-api: using in-memory store (set SCHEDULER_STORE=firestore to persist)")
		return store.NewMemoryStore()
	case "firestore":
		fs, err := store.NewFirestoreStore(context.Background(), projectID)
		if err != nil {
			log.Fatalf("scheduler-api: SCHEDULER_STORE=firestore but Firestore init failed: %v", err)
		}
		log.Printf("scheduler-api: using Firestore store (project %s)", projectID)
		return fs
	default:
		log.Fatalf("scheduler-api: unknown SCHEDULER_STORE=%q (want \"memory\" or \"firestore\")", os.Getenv("SCHEDULER_STORE"))
		return nil // unreachable
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
