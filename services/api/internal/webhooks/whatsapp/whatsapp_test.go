package whatsapp

// whatsapp_test.go exercises the report-only WhatsApp webhook receiver:
//   - GET verification handshake (token success + failure modes)
//   - POST signature verification (valid + invalid + missing)
//   - payload parsing of a realistic Meta inbound fixture
//   - the Sink receiving the parsed message end-to-end through EventHandler
//
// Tests follow the repo's table-driven, httptest.NewRecorder style (see
// internal/api/api_test.go). They are white-box (package whatsapp) so they can
// drive verifySignature/parsePayload directly and assert on MemorySink state.

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
)

// realisticInboundFixture is a representative WhatsApp Business Cloud API
// inbound text-message webhook body, trimmed to the fields this receiver reads.
const realisticInboundFixture = `{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "102290129340398",
      "changes": [
        {
          "field": "messages",
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "15550009999",
              "phone_number_id": "106540352242922"
            },
            "contacts": [
              {
                "profile": { "name": "Dana Cohen" },
                "wa_id": "972501112233"
              }
            ],
            "messages": [
              {
                "from": "972501112233",
                "id": "wamid.HBgMOTcyNTAxMTEyMjMzFQIAEhgUM0E5RjQ0",
                "timestamp": "1717880400",
                "type": "text",
                "text": { "body": "Hi, can I swap my Tuesday shift?" }
              }
            ]
          }
        }
      ]
    }
  ]
}`

// sign computes the X-Hub-Signature-256 header value Meta would send for body
// under secret.
func sign(secret string, body []byte) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	return signaturePrefix + hex.EncodeToString(mac.Sum(nil))
}

// -----------------------------------------------------------------------------
// GET verification handshake
// -----------------------------------------------------------------------------

func TestVerifyHandler(t *testing.T) {
	const token = "verify-secret-token"

	tests := []struct {
		name       string
		envToken   string // value of WHATSAPP_VERIFY_TOKEN for this case
		mode       string
		verifyTok  string
		challenge  string
		wantStatus int
		wantBody   string // expected body on success (the echoed challenge)
	}{
		{
			name:       "valid subscribe echoes challenge",
			envToken:   token,
			mode:       "subscribe",
			verifyTok:  token,
			challenge:  "1158201444",
			wantStatus: http.StatusOK,
			wantBody:   "1158201444",
		},
		{
			name:       "wrong token is forbidden",
			envToken:   token,
			mode:       "subscribe",
			verifyTok:  "not-the-token",
			challenge:  "1158201444",
			wantStatus: http.StatusForbidden,
		},
		{
			name:       "wrong mode is forbidden",
			envToken:   token,
			mode:       "unsubscribe",
			verifyTok:  token,
			challenge:  "1158201444",
			wantStatus: http.StatusForbidden,
		},
		{
			name:       "missing token is forbidden",
			envToken:   token,
			mode:       "subscribe",
			verifyTok:  "",
			challenge:  "1158201444",
			wantStatus: http.StatusForbidden,
		},
		{
			name:       "unconfigured server fails closed",
			envToken:   "", // no WHATSAPP_VERIFY_TOKEN set
			mode:       "subscribe",
			verifyTok:  "",
			challenge:  "1158201444",
			wantStatus: http.StatusForbidden,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Setenv(envVerifyToken, tt.envToken)

			req := httptest.NewRequest(http.MethodGet, "/webhooks/whatsapp", nil)
			q := req.URL.Query()
			q.Set("hub.mode", tt.mode)
			q.Set("hub.verify_token", tt.verifyTok)
			q.Set("hub.challenge", tt.challenge)
			req.URL.RawQuery = q.Encode()

			w := httptest.NewRecorder()
			VerifyHandler()(w, req)

			if w.Code != tt.wantStatus {
				t.Fatalf("status = %d, want %d (body: %q)", w.Code, tt.wantStatus, w.Body.String())
			}
			if tt.wantStatus == http.StatusOK && w.Body.String() != tt.wantBody {
				t.Errorf("body = %q, want %q (challenge must be echoed verbatim)", w.Body.String(), tt.wantBody)
			}
		})
	}
}

// -----------------------------------------------------------------------------
// HMAC signature verification (unit, via verifySignature)
// -----------------------------------------------------------------------------

func TestVerifySignature(t *testing.T) {
	const secret = "app-secret-abc123"
	body := []byte(`{"hello":"world"}`)
	valid := sign(secret, body)

	tests := []struct {
		name      string
		body      []byte
		header    string
		appSecret string
		want      bool
	}{
		{name: "valid signature", body: body, header: valid, appSecret: secret, want: true},
		{name: "tampered body fails", body: []byte(`{"hello":"mars"}`), header: valid, appSecret: secret, want: false},
		{name: "wrong secret fails", body: body, header: valid, appSecret: "other-secret", want: false},
		{name: "missing header fails", body: body, header: "", appSecret: secret, want: false},
		{name: "missing sha256 prefix fails", body: body, header: hex.EncodeToString([]byte("x")), appSecret: secret, want: false},
		{name: "non-hex content fails", body: body, header: signaturePrefix + "zzzz", appSecret: secret, want: false},
		{name: "empty app secret fails closed", body: body, header: valid, appSecret: "", want: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := verifySignature(tt.body, tt.header, tt.appSecret); got != tt.want {
				t.Errorf("verifySignature() = %v, want %v", got, tt.want)
			}
		})
	}
}

// -----------------------------------------------------------------------------
// POST EventHandler signature gate + ingestion
// -----------------------------------------------------------------------------

func TestEventHandlerSignatureGate(t *testing.T) {
	const secret = "app-secret-event"
	body := []byte(realisticInboundFixture)

	tests := []struct {
		name        string
		header      string
		wantStatus  int
		wantIngest  int // messages expected in the sink after the call
	}{
		{
			name:       "valid signature ingests",
			header:     sign(secret, body),
			wantStatus: http.StatusOK,
			wantIngest: 1,
		},
		{
			name:       "invalid signature is unauthorized and ingests nothing",
			header:     signaturePrefix + hex.EncodeToString([]byte("deadbeefdeadbeef")),
			wantStatus: http.StatusUnauthorized,
			wantIngest: 0,
		},
		{
			name:       "missing signature is unauthorized and ingests nothing",
			header:     "",
			wantStatus: http.StatusUnauthorized,
			wantIngest: 0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Setenv(envAppSecret, secret)

			sink := NewMemorySink(nil)
			req := httptest.NewRequest(http.MethodPost, "/webhooks/whatsapp", bytes.NewReader(body))
			if tt.header != "" {
				req.Header.Set("X-Hub-Signature-256", tt.header)
			}
			w := httptest.NewRecorder()
			EventHandler(sink)(w, req)

			if w.Code != tt.wantStatus {
				t.Fatalf("status = %d, want %d (body: %q)", w.Code, tt.wantStatus, w.Body.String())
			}
			if sink.Len() != tt.wantIngest {
				t.Errorf("sink ingested %d messages, want %d", sink.Len(), tt.wantIngest)
			}
		})
	}
}

// TestEventHandlerDeliversParsedMessage asserts the Sink receives the fully
// parsed inbound message (the core "did the parsed message reach the sink"
// contract).
func TestEventHandlerDeliversParsedMessage(t *testing.T) {
	const secret = "app-secret-deliver"
	t.Setenv(envAppSecret, secret)

	body := []byte(realisticInboundFixture)
	sink := NewMemorySink(nil)

	req := httptest.NewRequest(http.MethodPost, "/webhooks/whatsapp", bytes.NewReader(body))
	req.Header.Set("X-Hub-Signature-256", sign(secret, body))
	w := httptest.NewRecorder()
	EventHandler(sink)(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body: %q)", w.Code, w.Body.String())
	}

	msgs := sink.Messages()
	if len(msgs) != 1 {
		t.Fatalf("sink got %d messages, want 1", len(msgs))
	}
	m := msgs[0]
	if m.MessageID != "wamid.HBgMOTcyNTAxMTEyMjMzFQIAEhgUM0E5RjQ0" {
		t.Errorf("MessageID = %q", m.MessageID)
	}
	if m.From != "972501112233" {
		t.Errorf("From = %q, want 972501112233", m.From)
	}
	if m.Type != "text" {
		t.Errorf("Type = %q, want text", m.Type)
	}
	if m.Text != "Hi, can I swap my Tuesday shift?" {
		t.Errorf("Text = %q", m.Text)
	}
	if m.ProfileName != "Dana Cohen" {
		t.Errorf("ProfileName = %q, want Dana Cohen", m.ProfileName)
	}
	if m.PhoneNumberID != "106540352242922" {
		t.Errorf("PhoneNumberID = %q, want 106540352242922", m.PhoneNumberID)
	}
	if m.Timestamp != "1717880400" {
		t.Errorf("Timestamp = %q, want 1717880400", m.Timestamp)
	}
	if m.ReceivedAt == "" {
		t.Errorf("ReceivedAt should be stamped by the receiver")
	}
}

// -----------------------------------------------------------------------------
// Payload parsing
// -----------------------------------------------------------------------------

func TestParsePayload(t *testing.T) {
	t.Run("parses realistic inbound fixture", func(t *testing.T) {
		msgs, err := parsePayload([]byte(realisticInboundFixture), "2026-06-08T00:00:00Z")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(msgs) != 1 {
			t.Fatalf("got %d messages, want 1", len(msgs))
		}
		if msgs[0].Text != "Hi, can I swap my Tuesday shift?" {
			t.Errorf("Text = %q", msgs[0].Text)
		}
		if msgs[0].ProfileName != "Dana Cohen" {
			t.Errorf("ProfileName = %q", msgs[0].ProfileName)
		}
		if msgs[0].ReceivedAt != "2026-06-08T00:00:00Z" {
			t.Errorf("ReceivedAt = %q, want stamped value", msgs[0].ReceivedAt)
		}
	})

	t.Run("flattens multiple entries/changes/messages", func(t *testing.T) {
		const multi = `{
		  "object": "whatsapp_business_account",
		  "entry": [
		    {"changes": [
		      {"field":"messages","value":{
		        "metadata":{"phone_number_id":"PN1"},
		        "contacts":[{"wa_id":"111","profile":{"name":"Alice"}}],
		        "messages":[
		          {"from":"111","id":"m1","timestamp":"100","type":"text","text":{"body":"one"}},
		          {"from":"111","id":"m2","timestamp":"101","type":"text","text":{"body":"two"}}
		        ]
		      }}
		    ]},
		    {"changes": [
		      {"field":"messages","value":{
		        "metadata":{"phone_number_id":"PN2"},
		        "contacts":[{"wa_id":"222","profile":{"name":"Bob"}}],
		        "messages":[
		          {"from":"222","id":"m3","timestamp":"102","type":"text","text":{"body":"three"}}
		        ]
		      }}
		    ]}
		  ]
		}`
		msgs, err := parsePayload([]byte(multi), "ts")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(msgs) != 3 {
			t.Fatalf("got %d messages, want 3", len(msgs))
		}
		// Profile names must match the correct sender within each change.
		got := map[string]string{}
		for _, m := range msgs {
			got[m.MessageID] = m.ProfileName + "|" + m.PhoneNumberID
		}
		if got["m1"] != "Alice|PN1" || got["m2"] != "Alice|PN1" || got["m3"] != "Bob|PN2" {
			t.Errorf("name/phone mapping wrong: %v", got)
		}
	})

	t.Run("status-only callback yields no messages", func(t *testing.T) {
		const statusOnly = `{
		  "object":"whatsapp_business_account",
		  "entry":[{"changes":[{"field":"messages","value":{
		    "metadata":{"phone_number_id":"PN"},
		    "statuses":[{"id":"wamid.x","status":"delivered"}]
		  }}]}]
		}`
		msgs, err := parsePayload([]byte(statusOnly), "ts")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(msgs) != 0 {
			t.Errorf("got %d messages, want 0 for a status-only callback", len(msgs))
		}
	})

	t.Run("non-text message keeps empty text body", func(t *testing.T) {
		const img = `{
		  "object":"whatsapp_business_account",
		  "entry":[{"changes":[{"field":"messages","value":{
		    "metadata":{"phone_number_id":"PN"},
		    "messages":[{"from":"333","id":"m9","timestamp":"103","type":"image","text":{"body":"should-be-ignored"}}]
		  }}]}]
		}`
		msgs, err := parsePayload([]byte(img), "ts")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(msgs) != 1 {
			t.Fatalf("got %d messages, want 1", len(msgs))
		}
		if msgs[0].Type != "image" {
			t.Errorf("Type = %q, want image", msgs[0].Type)
		}
		if msgs[0].Text != "" {
			t.Errorf("Text = %q, want empty for non-text type", msgs[0].Text)
		}
	})

	t.Run("malformed JSON returns an error", func(t *testing.T) {
		if _, err := parsePayload([]byte("{not json"), "ts"); err == nil {
			t.Error("expected an error for malformed JSON, got nil")
		}
	})
}

// -----------------------------------------------------------------------------
// MemorySink behavior
// -----------------------------------------------------------------------------

func TestMemorySinkAppendOnlyConcurrent(t *testing.T) {
	sink := NewMemorySink(nil)
	const n = 50
	var wg sync.WaitGroup
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			_ = sink.Deliver(context.Background(), InboundMessage{MessageID: "m", Type: "text"})
		}(i)
	}
	wg.Wait()
	if sink.Len() != n {
		t.Errorf("sink.Len() = %d, want %d", sink.Len(), n)
	}
	// Messages() returns a copy: mutating it must not affect the store.
	snap := sink.Messages()
	if len(snap) != n {
		t.Fatalf("snapshot len = %d, want %d", len(snap), n)
	}
	snap[0].Text = "mutated"
	if sink.Messages()[0].Text == "mutated" {
		t.Error("Messages() must return a copy; store was mutated through it")
	}
}

// -----------------------------------------------------------------------------
// Slack-notify decorator (OFF by default)
// -----------------------------------------------------------------------------

// fakeNotifier records calls so the test can assert the decorator fired.
type fakeNotifier struct {
	mu    sync.Mutex
	count int
}

func (f *fakeNotifier) Notify(_ context.Context, _ InboundMessage) error {
	f.mu.Lock()
	f.count++
	f.mu.Unlock()
	return nil
}

func TestMaybeSlackNotify(t *testing.T) {
	t.Run("disabled by default returns inner unchanged", func(t *testing.T) {
		t.Setenv("WHATSAPP_NOTIFY_SLACK", "") // explicitly unset/empty
		inner := NewMemorySink(nil)
		got := MaybeSlackNotify(inner, &fakeNotifier{})
		if got != Sink(inner) {
			t.Errorf("with flag OFF, MaybeSlackNotify must return the inner sink unchanged")
		}
	})

	t.Run("falsey values keep it disabled", func(t *testing.T) {
		for _, v := range []string{"0", "false", "no", "off", "nope"} {
			t.Setenv("WHATSAPP_NOTIFY_SLACK", v)
			inner := NewMemorySink(nil)
			if MaybeSlackNotify(inner, &fakeNotifier{}) != Sink(inner) {
				t.Errorf("value %q must keep the decorator disabled", v)
			}
		}
	})

	t.Run("enabled forwards to internal notifier AND still persists", func(t *testing.T) {
		t.Setenv("WHATSAPP_NOTIFY_SLACK", "true")
		inner := NewMemorySink(nil)
		notifier := &fakeNotifier{}
		decorated := MaybeSlackNotify(inner, notifier)
		if decorated == Sink(inner) {
			t.Fatal("with flag ON and a notifier, expected a decorator, got the inner sink")
		}
		if err := decorated.Deliver(context.Background(), InboundMessage{MessageID: "m1", Type: "text"}); err != nil {
			t.Fatalf("Deliver error: %v", err)
		}
		if inner.Len() != 1 {
			t.Errorf("inner sink persisted %d, want 1 (decorator must still persist)", inner.Len())
		}
		if notifier.count != 1 {
			t.Errorf("notifier fired %d times, want 1", notifier.count)
		}
	})

	t.Run("enabled but nil notifier stays inner (no send path)", func(t *testing.T) {
		t.Setenv("WHATSAPP_NOTIFY_SLACK", "1")
		inner := NewMemorySink(nil)
		if MaybeSlackNotify(inner, nil) != Sink(inner) {
			t.Error("nil notifier must return the inner sink even when the flag is on")
		}
	})
}
