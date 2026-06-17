package whatsapp

// media_test.go exercises INBOUND media retrieval for the report-only WhatsApp
// receiver:
//   - a media inbound resolves the lookaside URL with a Bearer header, downloads
//     the bytes, and stores them under the correct key/mime (fake Graph + fake
//     store, NO network, NO real GCS)
//   - missing token/bucket -> deferred, with zero Graph calls and no panic
//   - a text message -> unchanged path (no media record, no calls)
//   - an unsupported kind -> flagged "open in app"
//
// Tests are white-box (package whatsapp) and use injected fakes, mirroring the
// table-driven style in whatsapp_test.go. They never touch the network.

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

// -----------------------------------------------------------------------------
// Fakes — injected GraphClient + MediaStore. No network, no GCS.
// -----------------------------------------------------------------------------

// fakeGraphCall records a single Get invocation so tests can assert on the URL
// and the Bearer token that was attached.
type fakeGraphCall struct {
	url    string
	bearer string
}

// fakeGraphClient is an injectable GraphClient that returns canned responses
// keyed by URL and records every call (so a test can assert the Bearer header
// travelled with BOTH the metadata resolve and the lookaside download).
type fakeGraphClient struct {
	mu        sync.Mutex
	calls     []fakeGraphCall
	responses map[string]*http.Response // url -> response
	errFor    map[string]error          // url -> error to return
}

func newFakeGraphClient() *fakeGraphClient {
	return &fakeGraphClient{
		responses: map[string]*http.Response{},
		errFor:    map[string]error{},
	}
}

// stub registers a 200 JSON/body response for an exact url.
func (f *fakeGraphClient) stub(url, body string) {
	f.responses[url] = &http.Response{
		StatusCode: http.StatusOK,
		Body:       io.NopCloser(strings.NewReader(body)),
		Header:     http.Header{},
	}
}

// stubStatus registers a non-200 response for an exact url.
func (f *fakeGraphClient) stubStatus(url string, status int) {
	f.responses[url] = &http.Response{
		StatusCode: status,
		Body:       io.NopCloser(strings.NewReader("")),
		Header:     http.Header{},
	}
}

func (f *fakeGraphClient) Get(_ context.Context, url, bearer string) (*http.Response, error) {
	f.mu.Lock()
	f.calls = append(f.calls, fakeGraphCall{url: url, bearer: bearer})
	f.mu.Unlock()
	if err := f.errFor[url]; err != nil {
		return nil, err
	}
	if resp, ok := f.responses[url]; ok {
		return resp, nil
	}
	// Unstubbed URL -> 404 so a wrong URL surfaces as a clear failure.
	return &http.Response{StatusCode: http.StatusNotFound, Body: io.NopCloser(strings.NewReader("")), Header: http.Header{}}, nil
}

func (f *fakeGraphClient) callCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.calls)
}

// putRecord captures one MediaStore.Put.
type putRecord struct {
	key         string
	contentType string
	data        []byte
}

// fakeMediaStore is an injectable MediaStore that buffers bytes in memory and
// records every Put. It returns a gs://-style ref derived from a fixed fake
// bucket so tests can assert the StorageRef shape.
type fakeMediaStore struct {
	mu     sync.Mutex
	puts   []putRecord
	bucket string
	putErr error // when set, Put fails (to exercise the error path)
}

func newFakeMediaStore() *fakeMediaStore {
	return &fakeMediaStore{bucket: "fake-bucket"}
}

func (s *fakeMediaStore) Put(_ context.Context, key, contentType string, r io.Reader) (string, int64, error) {
	if s.putErr != nil {
		return "", 0, s.putErr
	}
	data, err := io.ReadAll(r)
	if err != nil {
		return "", 0, err
	}
	s.mu.Lock()
	s.puts = append(s.puts, putRecord{key: key, contentType: contentType, data: data})
	s.mu.Unlock()
	return "gs://" + s.bucket + "/" + key, int64(len(data)), nil
}

func (s *fakeMediaStore) putCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.puts)
}

// -----------------------------------------------------------------------------
// Test fixtures
// -----------------------------------------------------------------------------

// imageInboundFixture is a realistic image-media inbound webhook body.
const imageInboundFixture = `{
  "object": "whatsapp_business_account",
  "entry": [{
    "changes": [{
      "field": "messages",
      "value": {
        "metadata": {"phone_number_id": "106540352242922"},
        "contacts": [{"profile": {"name": "Dana Cohen"}, "wa_id": "972501112233"}],
        "messages": [{
          "from": "972501112233",
          "id": "wamid.IMG1",
          "timestamp": "1717880400",
          "type": "image",
          "image": {"id": "media-id-9988", "mime_type": "image/jpeg", "sha256": "abc"}
        }]
      }
    }]
  }]
}`

// documentInboundFixture carries a filename so we can assert it survives onto
// the storage key.
const documentInboundFixture = `{
  "object": "whatsapp_business_account",
  "entry": [{"changes": [{"field": "messages","value": {
    "metadata": {"phone_number_id": "PN"},
    "messages": [{
      "from": "111", "id": "wamid.DOC1", "timestamp": "100", "type": "document",
      "document": {"id": "doc-id-7", "mime_type": "application/pdf", "filename": "roster.pdf"}
    }]
  }}]}]
}`

// helper: the Graph metadata URL the resolver will hit for a media id.
func metaURLFor(mr *MediaResolver, id string) string {
	return graphBaseURL + "/" + mr.version + "/" + id
}

// -----------------------------------------------------------------------------
// parseMediaRefs
// -----------------------------------------------------------------------------

func TestParseMediaRefs(t *testing.T) {
	t.Run("extracts image media ref", func(t *testing.T) {
		refs, err := parseMediaRefs([]byte(imageInboundFixture))
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(refs) != 1 {
			t.Fatalf("got %d refs, want 1", len(refs))
		}
		r := refs[0]
		if r.kind != "image" || r.id != "media-id-9988" || r.mimeType != "image/jpeg" {
			t.Errorf("ref = %+v, want image/media-id-9988/image/jpeg", r)
		}
		if r.messageID != "wamid.IMG1" {
			t.Errorf("messageID = %q", r.messageID)
		}
	})

	t.Run("extracts document filename", func(t *testing.T) {
		refs, err := parseMediaRefs([]byte(documentInboundFixture))
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(refs) != 1 || refs[0].filename != "roster.pdf" {
			t.Fatalf("refs = %+v, want one with filename roster.pdf", refs)
		}
	})

	t.Run("text message yields no media refs", func(t *testing.T) {
		refs, err := parseMediaRefs([]byte(realisticInboundFixture))
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(refs) != 0 {
			t.Errorf("got %d refs for a text message, want 0", len(refs))
		}
	})

	t.Run("malformed JSON returns an error", func(t *testing.T) {
		if _, err := parseMediaRefs([]byte("{not json")); err == nil {
			t.Error("expected an error for malformed JSON, got nil")
		}
	})
}

// -----------------------------------------------------------------------------
// Resolve — the happy path: resolve lookaside URL with Bearer, download, store.
// -----------------------------------------------------------------------------

func TestResolveStoresMediaWithBearerAndKey(t *testing.T) {
	t.Setenv(envMediaToken, "graph-token-xyz")
	t.Setenv(envMediaBucket, "media-bucket")

	const mediaID = "media-id-9988"
	const lookaside = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?asset=ABC&token=short"
	const imageBytes = "\xFF\xD8\xFFfake-jpeg-bytes"

	client := newFakeGraphClient()
	store := newFakeMediaStore()
	mr := NewMediaResolver(client, store)

	// Step 1: metadata resolve returns the short-lived lookaside URL + mime.
	client.stub(metaURLFor(mr, mediaID),
		`{"url":"`+lookaside+`","mime_type":"image/jpeg","file_size":16,"id":"`+mediaID+`"}`)
	// Step 2: the lookaside URL returns the bytes.
	client.stub(lookaside, imageBytes)

	refs, err := parseMediaRefs([]byte(imageInboundFixture))
	if err != nil || len(refs) != 1 {
		t.Fatalf("fixture parse: err=%v refs=%d", err, len(refs))
	}

	rec := mr.Resolve(context.Background(), refs[0])

	if rec.Status != MediaStatusStored {
		t.Fatalf("Status = %q, want stored (detail: %q)", rec.Status, rec.Detail)
	}
	// StorageRef must be the stable gs:// reference keyed by the media id.
	wantRef := "gs://" + store.bucket + "/whatsapp/media/" + mediaID
	if rec.StorageRef != wantRef {
		t.Errorf("StorageRef = %q, want %q", rec.StorageRef, wantRef)
	}
	if rec.MimeType != "image/jpeg" {
		t.Errorf("MimeType = %q, want image/jpeg", rec.MimeType)
	}
	if rec.SizeBytes != int64(len(imageBytes)) {
		t.Errorf("SizeBytes = %d, want %d", rec.SizeBytes, len(imageBytes))
	}

	// Exactly one object was stored, with the right key/mime/bytes.
	if store.putCount() != 1 {
		t.Fatalf("store.putCount() = %d, want 1", store.putCount())
	}
	put := store.puts[0]
	if put.key != "whatsapp/media/"+mediaID {
		t.Errorf("store key = %q, want whatsapp/media/%s", put.key, mediaID)
	}
	if put.contentType != "image/jpeg" {
		t.Errorf("store contentType = %q, want image/jpeg", put.contentType)
	}
	if !bytes.Equal(put.data, []byte(imageBytes)) {
		t.Errorf("stored bytes mismatch: got %q", put.data)
	}

	// BOTH Graph calls (resolve + download) must carry the Bearer token.
	if client.callCount() != 2 {
		t.Fatalf("Graph calls = %d, want 2 (resolve + download)", client.callCount())
	}
	for i, c := range client.calls {
		if c.bearer != "graph-token-xyz" {
			t.Errorf("call %d (%s) bearer = %q, want graph-token-xyz", i, c.url, c.bearer)
		}
	}
	if client.calls[0].url != metaURLFor(mr, mediaID) {
		t.Errorf("first call url = %q, want metadata resolve", client.calls[0].url)
	}
	if client.calls[1].url != lookaside {
		t.Errorf("second call url = %q, want lookaside download", client.calls[1].url)
	}
}

// SSRF / token-exfil guard: a metadata response whose download URL points off a
// Meta-owned host must be REJECTED before the Bearer-authenticated download GET —
// degrading to MediaStatusError, never sending the token to the attacker host and
// never storing anything.
func TestResolveRejectsNonMetaDownloadHost(t *testing.T) {
	t.Setenv(envMediaToken, "graph-token-xyz")
	t.Setenv(envMediaBucket, "media-bucket")

	const mediaID = "media-id-evil"
	const evil = "https://evil.example.com/steal?asset=ABC"

	client := newFakeGraphClient()
	store := newFakeMediaStore()
	mr := NewMediaResolver(client, store)

	// metadata resolve returns an attacker-chosen download URL.
	client.stub(metaURLFor(mr, mediaID),
		`{"url":"`+evil+`","mime_type":"image/jpeg","file_size":16,"id":"`+mediaID+`"}`)
	// deliberately DO NOT stub `evil` — the download must never be attempted.

	refs, err := parseMediaRefs([]byte(imageInboundFixture))
	if err != nil || len(refs) != 1 {
		t.Fatalf("fixture parse: err=%v refs=%d", err, len(refs))
	}
	// give the ref the evil media id so the metadata stub matches
	refs[0].id = mediaID

	rec := mr.Resolve(context.Background(), refs[0])

	if rec.Status != MediaStatusError {
		t.Fatalf("Status = %q, want error (detail: %q)", rec.Status, rec.Detail)
	}
	if !strings.Contains(rec.Detail, "not an allowed Meta media host") {
		t.Errorf("Detail = %q, want a host-allowlist rejection", rec.Detail)
	}
	// The download GET must NOT have happened — only the metadata resolve (1 call).
	if client.callCount() != 1 {
		t.Fatalf("Graph calls = %d, want 1 (resolve only; download blocked)", client.callCount())
	}
	if store.putCount() != 0 {
		t.Errorf("store.putCount() = %d, want 0 (nothing stored on a blocked download)", store.putCount())
	}
}

// allowedMediaHost / validateMediaURL: only https on Meta-owned hosts is permitted.
func TestAllowedMediaHostAndValidateURL(t *testing.T) {
	allow := []string{
		"https://graph.facebook.com/v21.0/123",
		"https://lookaside.fbsbx.com/x",
		"https://scontent.fbsbx.com/y",
		"https://LOOKASIDE.FBSBX.COM/z", // case-insensitive
	}
	deny := []string{
		"http://lookaside.fbsbx.com/x",     // not https
		"https://169.254.169.254/latest/",  // cloud metadata
		"https://localhost/x",              // loopback
		"https://evil.example.com/x",       // wrong host
		"https://lookaside.fbsbx.com.evil.com/x", // suffix-spoof
		"ftp://lookaside.fbsbx.com/x",      // wrong scheme
	}
	for _, u := range allow {
		if err := validateMediaURL(u); err != nil {
			t.Errorf("validateMediaURL(%q) = %v, want allowed", u, err)
		}
	}
	for _, u := range deny {
		if err := validateMediaURL(u); err == nil {
			t.Errorf("validateMediaURL(%q) = nil, want REJECTED", u)
		}
	}
}

func TestResolveDocumentKeyIncludesFilename(t *testing.T) {
	t.Setenv(envMediaToken, "tok")
	t.Setenv(envMediaBucket, "b")

	const mediaID = "doc-id-7"
	const lookaside = "https://lookaside.fbsbx.com/doc"

	client := newFakeGraphClient()
	store := newFakeMediaStore()
	mr := NewMediaResolver(client, store)
	client.stub(metaURLFor(mr, mediaID), `{"url":"`+lookaside+`","mime_type":"application/pdf"}`)
	client.stub(lookaside, "%PDF-1.7 bytes")

	refs, _ := parseMediaRefs([]byte(documentInboundFixture))
	rec := mr.Resolve(context.Background(), refs[0])

	if rec.Status != MediaStatusStored {
		t.Fatalf("Status = %q, want stored (detail %q)", rec.Status, rec.Detail)
	}
	wantKey := "whatsapp/media/" + mediaID + "/roster.pdf"
	if store.puts[0].key != wantKey {
		t.Errorf("store key = %q, want %q", store.puts[0].key, wantKey)
	}
}

// -----------------------------------------------------------------------------
// INERT WITHOUT CREDS — missing token or bucket -> deferred, NO calls, no panic.
// -----------------------------------------------------------------------------

func TestResolveDeferredWhenUnconfigured(t *testing.T) {
	cases := []struct {
		name   string
		token  string
		bucket string
	}{
		{name: "no token", token: "", bucket: "b"},
		{name: "no bucket", token: "t", bucket: ""},
		{name: "neither", token: "", bucket: ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv(envMediaToken, tc.token)
			t.Setenv(envMediaBucket, tc.bucket)

			client := newFakeGraphClient()
			store := newFakeMediaStore()
			mr := NewMediaResolver(client, store)

			refs, _ := parseMediaRefs([]byte(imageInboundFixture))
			rec := mr.Resolve(context.Background(), refs[0])

			if rec.Status != MediaStatusDeferred {
				t.Fatalf("Status = %q, want deferred", rec.Status)
			}
			// The media id must be preserved for a later credentialed pass.
			if rec.MediaID != "media-id-9988" {
				t.Errorf("MediaID = %q, want preserved media-id-9988", rec.MediaID)
			}
			// No network call, no store write.
			if client.callCount() != 0 {
				t.Errorf("Graph calls = %d, want 0 when unconfigured", client.callCount())
			}
			if store.putCount() != 0 {
				t.Errorf("store puts = %d, want 0 when unconfigured", store.putCount())
			}
		})
	}
}

// A nil store must also defer (it is part of "configured"), never panic.
func TestResolveDeferredWhenStoreNil(t *testing.T) {
	t.Setenv(envMediaToken, "t")
	t.Setenv(envMediaBucket, "b")

	client := newFakeGraphClient()
	mr := NewMediaResolver(client, nil) // store nil

	refs, _ := parseMediaRefs([]byte(imageInboundFixture))
	rec := mr.Resolve(context.Background(), refs[0])

	if rec.Status != MediaStatusDeferred {
		t.Fatalf("Status = %q, want deferred when store is nil", rec.Status)
	}
	if client.callCount() != 0 {
		t.Errorf("Graph calls = %d, want 0 when store nil", client.callCount())
	}
}

// -----------------------------------------------------------------------------
// Text message -> unchanged path (no media ref, MediaStatusNone, no calls).
// -----------------------------------------------------------------------------

func TestResolveTextMessageIsNoOp(t *testing.T) {
	t.Setenv(envMediaToken, "t")
	t.Setenv(envMediaBucket, "b")

	client := newFakeGraphClient()
	store := newFakeMediaStore()
	mr := NewMediaResolver(client, store)

	// A text message yields no media refs at all -> nothing to resolve.
	refs, err := parseMediaRefs([]byte(realisticInboundFixture))
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if len(refs) != 0 {
		t.Fatalf("text message produced %d media refs, want 0", len(refs))
	}

	// Resolving the zero mediaRef is a no-op.
	rec := mr.Resolve(context.Background(), mediaRef{})
	if rec.Status != MediaStatusNone {
		t.Errorf("Status = %q, want none for empty ref", rec.Status)
	}
	if client.callCount() != 0 || store.putCount() != 0 {
		t.Errorf("text path made calls=%d puts=%d, want 0/0", client.callCount(), store.putCount())
	}
}

// -----------------------------------------------------------------------------
// Unsupported kind -> flagged "open in app", never fails.
// -----------------------------------------------------------------------------

func TestResolveUnsupportedKindFlagged(t *testing.T) {
	t.Setenv(envMediaToken, "t")
	t.Setenv(envMediaBucket, "b")

	client := newFakeGraphClient()
	store := newFakeMediaStore()
	mr := NewMediaResolver(client, store)

	// A kind we deliberately don't support via the download path.
	rec := mr.Resolve(context.Background(), mediaRef{kind: "view_once", id: "vo-1"})

	if rec.Status != MediaStatusOpenInApp {
		t.Fatalf("Status = %q, want open_in_app", rec.Status)
	}
	if rec.Detail == "" {
		t.Error("expected a human-readable Detail for open_in_app")
	}
	if client.callCount() != 0 || store.putCount() != 0 {
		t.Errorf("unsupported kind made calls=%d puts=%d, want 0/0", client.callCount(), store.putCount())
	}
}

// A supported kind that carries no media id (e.g. stripped view-once) -> open in app.
func TestResolveSupportedKindNoIDFlagged(t *testing.T) {
	t.Setenv(envMediaToken, "t")
	t.Setenv(envMediaBucket, "b")

	mr := NewMediaResolver(newFakeGraphClient(), newFakeMediaStore())
	rec := mr.Resolve(context.Background(), mediaRef{kind: "image", id: ""})
	if rec.Status != MediaStatusOpenInApp {
		t.Errorf("Status = %q, want open_in_app for media kind with no id", rec.Status)
	}
}

// -----------------------------------------------------------------------------
// Error paths — never panic, never fail the webhook; surface MediaStatusError.
// -----------------------------------------------------------------------------

func TestResolveErrorPaths(t *testing.T) {
	const mediaID = "media-id-9988"

	t.Run("metadata resolve non-200 -> error", func(t *testing.T) {
		t.Setenv(envMediaToken, "t")
		t.Setenv(envMediaBucket, "b")
		client := newFakeGraphClient()
		store := newFakeMediaStore()
		mr := NewMediaResolver(client, store)
		client.stubStatus(metaURLFor(mr, mediaID), http.StatusUnauthorized)

		refs, _ := parseMediaRefs([]byte(imageInboundFixture))
		rec := mr.Resolve(context.Background(), refs[0])
		if rec.Status != MediaStatusError {
			t.Fatalf("Status = %q, want error", rec.Status)
		}
		if store.putCount() != 0 {
			t.Errorf("store wrote %d on resolve failure, want 0", store.putCount())
		}
	})

	t.Run("metadata with empty url -> error", func(t *testing.T) {
		t.Setenv(envMediaToken, "t")
		t.Setenv(envMediaBucket, "b")
		client := newFakeGraphClient()
		store := newFakeMediaStore()
		mr := NewMediaResolver(client, store)
		client.stub(metaURLFor(mr, mediaID), `{"mime_type":"image/jpeg"}`)

		refs, _ := parseMediaRefs([]byte(imageInboundFixture))
		rec := mr.Resolve(context.Background(), refs[0])
		if rec.Status != MediaStatusError {
			t.Fatalf("Status = %q, want error for missing url", rec.Status)
		}
	})

	t.Run("download transport error -> error", func(t *testing.T) {
		t.Setenv(envMediaToken, "t")
		t.Setenv(envMediaBucket, "b")
		const lookaside = "https://lookaside.fbsbx.com/x"
		client := newFakeGraphClient()
		store := newFakeMediaStore()
		mr := NewMediaResolver(client, store)
		client.stub(metaURLFor(mr, mediaID), `{"url":"`+lookaside+`","mime_type":"image/jpeg"}`)
		client.errFor[lookaside] = errors.New("connection reset")

		refs, _ := parseMediaRefs([]byte(imageInboundFixture))
		rec := mr.Resolve(context.Background(), refs[0])
		if rec.Status != MediaStatusError {
			t.Fatalf("Status = %q, want error on download failure", rec.Status)
		}
		if store.putCount() != 0 {
			t.Errorf("store wrote %d on download failure, want 0", store.putCount())
		}
	})

	t.Run("store error -> error", func(t *testing.T) {
		t.Setenv(envMediaToken, "t")
		t.Setenv(envMediaBucket, "b")
		const lookaside = "https://lookaside.fbsbx.com/y"
		client := newFakeGraphClient()
		store := newFakeMediaStore()
		store.putErr = errors.New("gcs down")
		mr := NewMediaResolver(client, store)
		client.stub(metaURLFor(mr, mediaID), `{"url":"`+lookaside+`","mime_type":"image/jpeg"}`)
		client.stub(lookaside, "bytes")

		refs, _ := parseMediaRefs([]byte(imageInboundFixture))
		rec := mr.Resolve(context.Background(), refs[0])
		if rec.Status != MediaStatusError {
			t.Fatalf("Status = %q, want error on store failure", rec.Status)
		}
	})
}

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

func TestMediaStorageKey(t *testing.T) {
	tests := []struct {
		id, filename, want string
	}{
		{"abc123", "", "whatsapp/media/abc123"},
		{"abc/123", "", "whatsapp/media/abc_123"},
		{"id1", "my file.pdf", "whatsapp/media/id1/my_file.pdf"},
		{"id1", "../escape", "whatsapp/media/id1/.._escape"},
	}
	for _, tt := range tests {
		if got := mediaStorageKey(tt.id, tt.filename); got != tt.want {
			t.Errorf("mediaStorageKey(%q,%q) = %q, want %q", tt.id, tt.filename, got, tt.want)
		}
	}
}

func TestGraphVersionDefaultAndOverride(t *testing.T) {
	t.Run("default when unset", func(t *testing.T) {
		t.Setenv(envGraphVersion, "")
		if got := graphVersion(); got != defaultGraphVersion {
			t.Errorf("graphVersion() = %q, want default %q", got, defaultGraphVersion)
		}
	})
	t.Run("override and trim slashes", func(t *testing.T) {
		t.Setenv(envGraphVersion, "/v20.0/")
		if got := graphVersion(); got != "v20.0" {
			t.Errorf("graphVersion() = %q, want v20.0", got)
		}
	})
}

// sanity: the HTTPGraphClient attaches the Bearer header and does only GETs.
func TestHTTPGraphClientAttachesBearer(t *testing.T) {
	var gotAuth, gotMethod string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		gotMethod = r.Method
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, "ok")
	}))
	defer srv.Close()

	c := NewHTTPGraphClient(srv.Client())
	resp, err := c.Get(context.Background(), srv.URL, "tok-123")
	if err != nil {
		t.Fatalf("Get error: %v", err)
	}
	defer drainClose(resp.Body)
	if gotMethod != http.MethodGet {
		t.Errorf("method = %q, want GET", gotMethod)
	}
	if gotAuth != "Bearer tok-123" {
		t.Errorf("Authorization = %q, want Bearer tok-123", gotAuth)
	}
}
