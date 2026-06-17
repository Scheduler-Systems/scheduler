package whatsapp

import (
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/Scheduler-Systems/scheduler-api/internal/httputil"
)

// Environment variable names. Documented here as the single source of truth;
// values are NEVER hardcoded and are read from the process environment (or, in
// production, a secret manager that injects them as env vars).
//
//   - envVerifyToken — shared token echoed by Meta during the GET handshake.
//   - envAppSecret   — Meta app secret used to HMAC-verify POST bodies.
//
// Two further secrets are documented for completeness but are intentionally
// UNUSED by this receiver, because it is report-only and never sends:
//
//   - WHATSAPP_PHONE_NUMBER_ID — the business number id (send-side only).
//   - WHATSAPP_ACCESS_TOKEN    — the Graph API send token (send-side only).
const (
	envVerifyToken = "WHATSAPP_VERIFY_TOKEN"
	envAppSecret   = "WHATSAPP_APP_SECRET"
)

// maxWebhookBodyBytes caps the inbound webhook body so a malicious caller cannot
// exhaust memory via io.ReadAll. 1 MB matches httputil.maxRequestBodyBytes; a
// legitimate WhatsApp event batch is far smaller.
const maxWebhookBodyBytes = 1 << 20 // 1 MB

// nowRFC3339 returns the current UTC time as RFC3339, matching the timestamp
// format used by the schedules handlers.
func nowRFC3339() string {
	return time.Now().UTC().Format(time.RFC3339)
}

// normalizeFlag lowercases and trims an env flag value for comparison.
func normalizeFlag(v string) string {
	return strings.ToLower(strings.TrimSpace(v))
}

// VerifyHandler handles Meta's GET webhook verification handshake.
//
// Meta calls the webhook URL with query params:
//
//	hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<nonce>
//
// When hub.mode == "subscribe" AND hub.verify_token equals the configured
// WHATSAPP_VERIFY_TOKEN, the handler echoes the raw hub.challenge value back
// with 200 and a text/plain content type (Meta expects the bare challenge in
// the body). Any mismatch — wrong mode, wrong/empty token, or an empty
// configured token — returns 403 and reveals nothing.
func VerifyHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		mode := q.Get("hub.mode")
		token := q.Get("hub.verify_token")
		challenge := q.Get("hub.challenge")

		expected := os.Getenv(envVerifyToken)

		// Fail closed if the deployment has no verify token configured, and
		// require an exact match on both mode and token.
		if expected == "" || mode != "subscribe" || token != expected {
			w.WriteHeader(http.StatusForbidden)
			return
		}

		// Echo the raw challenge as the body. Meta reads the response body
		// verbatim; it must be the challenge and nothing else.
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, challenge)
	}
}

// EventHandler handles the POST inbound-event callback from Meta.
//
// Flow:
//  1. Read the RAW body (signature is computed over the exact bytes Meta sent,
//     so we must not re-encode).
//  2. Verify X-Hub-Signature-256 == "sha256=" + hex(HMAC_SHA256(body, secret))
//     in constant time. On mismatch -> 401 and DO NOTHING (no parse, no
//     persist).
//  3. Parse the Meta payload into typed InboundMessage values.
//  4. Hand each parsed message to the Sink (ingest-only).
//  5. Return 200 so Meta marks the event delivered.
//
// There is no branch anywhere in this handler that sends a message to the
// customer — it is structurally report-only.
func EventHandler(sink Sink) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Read the raw body, bounded. We need the exact bytes for HMAC, so we
		// cannot use httputil.ReadJSON (which unmarshals and discards the raw
		// form).
		raw, err := io.ReadAll(io.LimitReader(r.Body, maxWebhookBodyBytes+1))
		if err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{"error": "read_error"})
			return
		}
		if len(raw) > maxWebhookBodyBytes {
			httputil.WriteJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"error": "payload_too_large"})
			return
		}

		// Verify the signature BEFORE doing anything with the body. A missing
		// or invalid signature yields 401 and no side effects.
		sig := r.Header.Get("X-Hub-Signature-256")
		if !verifySignature(raw, sig, os.Getenv(envAppSecret)) {
			httputil.WriteJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid_signature"})
			return
		}

		messages, err := parsePayload(raw, nowRFC3339())
		if err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid_payload"})
			return
		}

		// Hand each parsed message to the ingest-only sink. A sink error is
		// logged-but-acked: Meta retries non-2xx, and the append-only store is
		// the source of truth, so we avoid a redelivery storm for transient
		// persistence issues.
		delivered := 0
		for _, m := range messages {
			if derr := sink.Deliver(r.Context(), m); derr == nil {
				delivered++
			}
		}

		httputil.WriteJSON(w, http.StatusOK, map[string]interface{}{
			"received":  len(messages),
			"delivered": delivered,
		})
	}
}
