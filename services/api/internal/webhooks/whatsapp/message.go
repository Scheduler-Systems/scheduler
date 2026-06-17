// Package whatsapp implements a REPORT-ONLY WhatsApp Business Cloud API
// (Meta Graph API) webhook receiver.
//
// SAFETY CONTRACT — this package only INGESTS inbound customer messages. There
// is deliberately NO code path that sends, replies, or otherwise pushes any
// message back to a WhatsApp customer. The Meta access token
// (WHATSAPP_ACCESS_TOKEN) is intentionally unused: the receiver classifies and
// persists, surfacing drafts/suggestions for human review only. Any future
// outbound capability must be a separate, explicitly human-gated component —
// never wired into this receiver.
//
// The two HTTP entrypoints are:
//
//   - VerifyHandler — Meta's GET verification handshake (hub.challenge echo).
//   - EventHandler  — the POST inbound-event sink, gated on an
//     X-Hub-Signature-256 HMAC-SHA256 check against WHATSAPP_APP_SECRET.
//
// Parsed messages are handed to a Sink for persistence. The default Sink writes
// to a thread-safe append-only in-memory store and emits a structured JSON log
// line, mirroring how cmd/scheduler-api/main.go wires the in-memory store.
package whatsapp

// InboundMessage is the normalized, typed representation of a single inbound
// WhatsApp message extracted from a Meta webhook payload.
//
// It is intentionally read-only data: it carries everything needed to classify,
// draft a suggested reply for human review, or persist — but contains nothing
// that could itself send a message.
type InboundMessage struct {
	// MessageID is the Meta-assigned WhatsApp message id (entry.changes.value.messages[].id).
	MessageID string `json:"messageId"`
	// From is the sender's WhatsApp phone number in E.164-ish wa_id form
	// (entry.changes.value.messages[].from). This is a customer identifier;
	// treat it as PII.
	From string `json:"from"`
	// Timestamp is the Meta-supplied unix timestamp string for the message
	// (entry.changes.value.messages[].timestamp), kept as-is to avoid lossy
	// reparsing.
	Timestamp string `json:"timestamp"`
	// Type is the message type, e.g. "text", "image", "audio"
	// (entry.changes.value.messages[].type).
	Type string `json:"type"`
	// Text is the text body when Type == "text"
	// (entry.changes.value.messages[].text.body); empty otherwise.
	Text string `json:"text,omitempty"`
	// ProfileName is the sender's WhatsApp profile display name when present
	// (entry.changes.value.contacts[].profile.name), matched by wa_id.
	ProfileName string `json:"profileName,omitempty"`
	// PhoneNumberID is the business phone-number id the message was delivered
	// to (entry.changes.value.metadata.phone_number_id). Useful for routing
	// when multiple numbers share one webhook.
	PhoneNumberID string `json:"phoneNumberId,omitempty"`
	// ReceivedAt is the RFC3339 timestamp at which this receiver ingested the
	// message. Set by the receiver, not by Meta.
	ReceivedAt string `json:"receivedAt,omitempty"`
}
