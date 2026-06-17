package whatsapp

import (
	"context"
	"encoding/json"
	"log"
	"os"
	"sync"
)

// Sink is the destination for parsed inbound messages.
//
// Deliver MUST NOT send anything back to the customer. A Sink is an ingest-only
// boundary: persist, classify, draft-for-review, or notify an internal channel.
// Returning an error signals that delivery failed; the EventHandler logs it but
// still returns 200 to Meta (Meta retries non-2xx, and a persistence hiccup
// should not trigger an unbounded redelivery storm — re-ingestion is handled by
// the append-only store's natural idempotency at the application layer).
type Sink interface {
	Deliver(ctx context.Context, msg InboundMessage) error
}

// -----------------------------------------------------------------------------
// MemorySink — default append-only in-memory store + structured JSON log line.
// -----------------------------------------------------------------------------

// MemorySink is the default Sink. It appends every delivered message to a
// thread-safe, append-only in-memory slice and emits one structured JSON log
// line per message, mirroring how cmd/scheduler-api/main.go wires the in-memory
// store for the rest of the service.
//
// It is append-only by construction: there is no method to mutate or delete a
// stored message, only to append and to read a snapshot. This makes it a
// faithful audit log of what was ingested.
type MemorySink struct {
	mu       sync.RWMutex
	messages []InboundMessage
	logger   *log.Logger
}

// NewMemorySink returns an initialized MemorySink. If logger is nil it falls
// back to the standard library default logger (stderr), matching the
// log.Printf usage elsewhere in cmd/scheduler-api.
func NewMemorySink(logger *log.Logger) *MemorySink {
	if logger == nil {
		logger = log.New(os.Stderr, "", log.LstdFlags)
	}
	return &MemorySink{logger: logger}
}

// Deliver appends msg to the append-only store and logs a structured line.
// It never contacts the customer.
func (s *MemorySink) Deliver(_ context.Context, msg InboundMessage) error {
	s.mu.Lock()
	s.messages = append(s.messages, msg)
	count := len(s.messages)
	s.mu.Unlock()

	// Structured JSON log line. Marshal a flat envelope so log aggregators can
	// index it. We log the message id and type but keep the body, since this is
	// the ingest audit trail; downstream consumers redact as needed.
	line, err := json.Marshal(struct {
		Event   string         `json:"event"`
		Stored  int            `json:"storedCount"`
		Message InboundMessage `json:"message"`
	}{
		Event:   "whatsapp.inbound.ingested",
		Stored:  count,
		Message: msg,
	})
	if err != nil {
		// Marshalling InboundMessage should never fail; degrade gracefully.
		s.logger.Printf("whatsapp.inbound.ingested messageId=%s type=%s", msg.MessageID, msg.Type)
		return nil
	}
	s.logger.Printf("%s", line)
	return nil
}

// Messages returns a copy of the stored messages in arrival order. The copy
// prevents callers from mutating the append-only store through the returned
// slice's backing array.
func (s *MemorySink) Messages() []InboundMessage {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]InboundMessage, len(s.messages))
	copy(out, s.messages)
	return out
}

// Len returns the number of stored messages.
func (s *MemorySink) Len() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.messages)
}

// -----------------------------------------------------------------------------
// slackNotifyDecorator — optional, OFF by default, internal-notify only.
// -----------------------------------------------------------------------------

// SlackNotifier is the minimal capability the decorator needs to post an
// internal notification. Implementations post to an INTERNAL Slack channel for
// human triage — never to the customer. It is an interface so the wiring can
// stay free of any concrete Slack client (and so tests can assert on it without
// a network call).
type SlackNotifier interface {
	// Notify posts an internal, human-facing notification about an ingested
	// message. It must not message the customer.
	Notify(ctx context.Context, msg InboundMessage) error
}

// slackNotifyDecorator wraps an inner Sink and, when enabled, also forwards each
// delivered message to an internal SlackNotifier. It is constructed via
// MaybeSlackNotify, which keeps it disabled unless WHATSAPP_NOTIFY_SLACK is
// explicitly turned on.
type slackNotifyDecorator struct {
	inner    Sink
	notifier SlackNotifier
}

// Deliver delivers to the inner sink first (persistence is the source of
// truth), then best-effort notifies the internal Slack channel. A Slack failure
// does not fail the delivery: the message is already persisted, and Slack is
// only a convenience surface for humans.
func (d *slackNotifyDecorator) Deliver(ctx context.Context, msg InboundMessage) error {
	if err := d.inner.Deliver(ctx, msg); err != nil {
		return err
	}
	if d.notifier != nil {
		if err := d.notifier.Notify(ctx, msg); err != nil {
			// Best-effort: log via the notifier path is the caller's concern.
			// Swallow so a Slack outage never blocks ingestion.
			_ = err
		}
	}
	return nil
}

// slackNotifyEnabled reports whether the WHATSAPP_NOTIFY_SLACK env flag is
// turned on. It defaults to OFF: only the explicit truthy values "1", "true",
// "yes", and "on" (case-insensitive) enable it. Anything else — including unset,
// empty, "0", "false", or a typo — leaves the decorator disabled. This makes
// the safe state the default and an accidental value fail closed.
func slackNotifyEnabled() bool {
	switch normalizeFlag(os.Getenv("WHATSAPP_NOTIFY_SLACK")) {
	case "1", "true", "yes", "on":
		return true
	default:
		return false
	}
}

// MaybeSlackNotify returns inner unchanged unless the WHATSAPP_NOTIFY_SLACK flag
// is explicitly enabled AND a non-nil notifier is supplied, in which case it
// returns a decorator that also forwards to the internal Slack channel.
//
// The decorator never sends to the customer — SlackNotifier posts to an
// internal channel for human review only.
func MaybeSlackNotify(inner Sink, notifier SlackNotifier) Sink {
	if notifier == nil || !slackNotifyEnabled() {
		return inner
	}
	return &slackNotifyDecorator{inner: inner, notifier: notifier}
}
