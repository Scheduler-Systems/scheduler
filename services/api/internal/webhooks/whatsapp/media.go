package whatsapp

// media.go adds INBOUND media handling to the report-only WhatsApp receiver.
//
// SAFETY CONTRACT (unchanged): this code is strictly INBOUND. It only retrieves
// media that a customer already SENT to us and stores it durably to our own
// object store. There is deliberately NO send/reply path here — fetching media
// we received is a read against the Meta Graph API, not a message to a customer.
//
// Why durable storage is required: a media message does not carry the bytes.
// It carries a Meta media id. Resolving that id yields a SHORT-LIVED (~5 min)
// lookaside download URL. If we let that URL expire we permanently lose the
// attachment, so we copy the bytes into our own bucket (keyed by the wa media
// id) the moment we receive the message.
//
// INERT WITHOUT CREDS: if WHATSAPP_TOKEN or WHATSAPP_MEDIA_BUCKET is unset, this
// code does NOT call out and does NOT crash. It marks the media "deferred" and
// continues, so the package is safe to build and merge before deploy
// credentials exist. Unsupported inbound kinds (e.g. view-once / group) are
// flagged "open in app" rather than failing the webhook.
//
// Testability: the Graph HTTP client and the object store are INJECTABLE
// interfaces (GraphClient, MediaStore). Tests inject fakes and hit NO network
// and need NO real GCS.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// Environment variable names for inbound media retrieval. As with the rest of
// the package these are the single source of truth and are NEVER hardcoded;
// values come from the process environment (or a secret manager that injects
// them as env vars).
//
//   - envMediaToken  — Graph API bearer token used to resolve + download media.
//   - envMediaBucket — name of the object-store bucket media bytes are copied
//     into for durable retention past the ~5-min lookaside URL expiry.
//   - envGraphVersion — Graph API version segment (e.g. "v21.0"). Optional;
//     defaultGraphVersion is used when unset.
//
// envMediaToken is the SAME Graph token Meta documents for media retrieval. It
// is read here ONLY to GET media we received; it is never used to send.
const (
	envMediaToken   = "WHATSAPP_TOKEN"
	envMediaBucket  = "WHATSAPP_MEDIA_BUCKET"
	envGraphVersion = "WHATSAPP_GRAPH_VERSION"
)

// defaultGraphVersion is used when WHATSAPP_GRAPH_VERSION is unset. Pinned to a
// recent stable Graph version; override via env to track Meta's deprecations
// without a code change.
const defaultGraphVersion = "v21.0"

// graphBaseURL is the Meta Graph API origin. Media metadata is resolved at
// graphBaseURL/<version>/<media-id>; the returned lookaside download URL is an
// absolute URL under a Meta-owned host and is used verbatim.
const graphBaseURL = "https://graph.facebook.com"

// allowedMediaHost reports whether host is a Meta-owned host we will send the
// Graph Bearer token to. The download URL in a media-metadata response is
// attacker-influenced data (it comes from the Graph JSON, not from us), so we
// MUST NOT GET it with the Bearer attached unless its host is on this allowlist
// — otherwise a spoofed/buggy Graph response (or any future code that lets an
// attacker-shaped URL reach this path) could point an authenticated request at
// an internal address (e.g. 169.254.169.254, localhost) and exfiltrate the
// token (SSRF). We allow graph.facebook.com (where we resolve metadata) and the
// lookaside media host family (*.fbsbx.com). Port is ignored; matching is
// case-insensitive. Anything else is rejected.
func allowedMediaHost(host string) bool {
	h := strings.ToLower(strings.TrimSpace(host))
	if i := strings.LastIndex(h, ":"); i != -1 && !strings.Contains(h[i:], "]") {
		h = h[:i] // strip :port (but not an IPv6 "::" segment)
	}
	return h == "graph.facebook.com" || h == "lookaside.fbsbx.com" || strings.HasSuffix(h, ".fbsbx.com")
}

// validateMediaURL rejects any download URL that is not an https URL on a
// Meta-owned host (see allowedMediaHost). It is the gate in front of the
// Bearer-authenticated byte download, defending against SSRF + token exfil via a
// malicious/buggy Graph metadata response.
func validateMediaURL(raw string) error {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return fmt.Errorf("download url parse: %w", err)
	}
	if u.Scheme != "https" {
		return fmt.Errorf("download url scheme %q not allowed (https required)", u.Scheme)
	}
	if !allowedMediaHost(u.Hostname()) {
		return fmt.Errorf("download url host %q not an allowed Meta media host", u.Hostname())
	}
	return nil
}

// mediaFetchTimeout bounds each Graph call (metadata resolve + byte download)
// so a slow Meta response cannot wedge webhook processing. The lookaside URL is
// only valid ~5 min, so there is no value in waiting long.
const mediaFetchTimeout = 30 * time.Second

// maxMediaBytes caps a single downloaded attachment. WhatsApp's own media size
// ceiling is ~100 MB (documents); we bound at 128 MB so a hostile or corrupt
// Content-Length cannot make us buffer unbounded bytes. Anything larger is
// treated as a fetch error and flagged, never panicked on.
const maxMediaBytes = 128 << 20 // 128 MB

// MediaStatus is the disposition of an inbound media attachment after the
// receiver has attempted (or deliberately skipped) retrieval.
type MediaStatus string

const (
	// MediaStatusNone means the message carried no media to handle (e.g. a
	// plain text message). It is the zero value so a non-media message is
	// trivially MediaStatusNone.
	MediaStatusNone MediaStatus = ""
	// MediaStatusStored means the bytes were fetched from Meta and durably
	// written to the object store; StorageRef points at them.
	MediaStatusStored MediaStatus = "stored"
	// MediaStatusDeferred means retrieval was skipped because credentials or
	// the bucket are not configured. The media id is preserved so a later,
	// credentialed pass can fetch it (within Meta's retention window). No
	// network call was made.
	MediaStatusDeferred MediaStatus = "deferred"
	// MediaStatusOpenInApp means the inbound kind is not retrievable via the
	// media-download path (e.g. view-once or a group artifact) and a human
	// must open it in the WhatsApp app. Never fails the webhook.
	MediaStatusOpenInApp MediaStatus = "open_in_app"
	// MediaStatusError means retrieval was attempted but failed (network,
	// auth, oversize, or a malformed Graph response). The webhook still
	// succeeds; the error is captured for human triage.
	MediaStatusError MediaStatus = "error"
)

// MediaRecord is the result of attempting inbound media retrieval for a single
// message. It is a companion to InboundMessage (kept separate so the existing
// message.go type stays untouched) and is itself ingest-only data: it carries a
// stable internal reference to the stored bytes, never a way to send anything.
type MediaRecord struct {
	// Status is the disposition of the attachment (see MediaStatus).
	Status MediaStatus `json:"status"`
	// Kind is the WhatsApp media type, e.g. "image", "audio", "video",
	// "document", "voice", "sticker". Empty for a non-media message.
	Kind string `json:"kind,omitempty"`
	// MediaID is the Meta-assigned media id extracted from the inbound
	// message. Preserved even when Status is Deferred so a later credentialed
	// pass can resolve it.
	MediaID string `json:"mediaId,omitempty"`
	// MimeType is the attachment mime type as reported by the inbound message
	// (and confirmed by the Graph metadata when fetched), e.g. "image/jpeg".
	MimeType string `json:"mimeType,omitempty"`
	// Filename is the original filename when the sender supplied one (documents
	// commonly do). Empty otherwise.
	Filename string `json:"filename,omitempty"`
	// StorageRef is the stable internal reference to the durably stored bytes,
	// in the form "gs://<bucket>/<key>". Populated only when Status==Stored.
	StorageRef string `json:"storageRef,omitempty"`
	// SizeBytes is the number of bytes written to the store when Status==Stored.
	SizeBytes int64 `json:"sizeBytes,omitempty"`
	// Detail is a short, human-readable note for Deferred/OpenInApp/Error
	// dispositions. It NEVER contains secret values or raw message bytes.
	Detail string `json:"detail,omitempty"`
}

// supportedMediaKinds is the set of inbound message types that carry a
// retrievable media id resolvable via the Graph media-download path. "voice" is
// WhatsApp's voice-note variant of audio; "sticker" carries an image-like id.
var supportedMediaKinds = map[string]bool{
	"image":    true,
	"audio":    true,
	"video":    true,
	"document": true,
	"voice":    true,
	"sticker":  true,
}

// GraphClient is the minimal HTTP capability media retrieval needs. It is an
// interface so tests inject a fake that returns canned responses and the
// production wiring injects a *http.Client (which satisfies it via
// HTTPGraphClient). It does only GETs — there is no send capability here.
type GraphClient interface {
	// Get performs an authenticated GET. The implementation attaches the
	// "Authorization: Bearer <token>" header. The caller owns closing the
	// returned body.
	Get(ctx context.Context, url, bearer string) (*http.Response, error)
}

// MediaStore is the durable object-store sink for media bytes. It is an
// interface so tests use an in-memory fake and production injects a GCS-backed
// implementation. Put copies the bytes under key within the configured bucket
// and returns the stable "gs://<bucket>/<key>" reference.
//
// A MediaStore is write-for-retention only: it persists what we received. It
// has no concept of, and no path to, sending anything to a customer.
type MediaStore interface {
	// Put streams r into the store at key, tagging it with contentType. It
	// returns the bytes written and the stable storage reference. Bucket
	// selection is the implementation's concern (from its own config), so the
	// returned ref is self-describing.
	Put(ctx context.Context, key, contentType string, r io.Reader) (ref string, size int64, err error)
}

// MediaResolver retrieves inbound media and stores it durably. It is the
// injectable seam the handler uses; both collaborators are interfaces so the
// whole path is testable with no network and no real GCS.
type MediaResolver struct {
	// client resolves media metadata and downloads bytes from Meta.
	client GraphClient
	// store durably persists downloaded bytes.
	store MediaStore
	// token is the Graph bearer token. Empty => inert (deferred).
	token string
	// bucket is the configured object-store bucket name. Empty => inert
	// (deferred). It is carried for diagnostics; the MediaStore owns the
	// authoritative bucket.
	bucket string
	// version is the Graph API version segment.
	version string
}

// graphVersion returns the configured Graph API version or the default. The
// returned value never has a leading slash.
func graphVersion() string {
	v := strings.Trim(strings.TrimSpace(os.Getenv(envGraphVersion)), "/")
	if v == "" {
		return defaultGraphVersion
	}
	return v
}

// NewMediaResolver constructs a resolver from the environment plus injected
// collaborators. It reads the Graph token and bucket from env (never logging
// their values). When the token or bucket is unset, or when store is nil, the
// resolver is INERT: Resolve returns a Deferred record and makes no network
// call. This is what makes the package safe to build and merge before deploy
// credentials exist.
//
// client may be nil; if so, and the resolver would otherwise be active, an
// HTTPGraphClient over http.DefaultClient is used. (When inert, the client is
// never touched.)
func NewMediaResolver(client GraphClient, store MediaStore) *MediaResolver {
	if client == nil {
		client = NewHTTPGraphClient(nil)
	}
	return &MediaResolver{
		client:  client,
		store:   store,
		token:   strings.TrimSpace(os.Getenv(envMediaToken)),
		bucket:  strings.TrimSpace(os.Getenv(envMediaBucket)),
		version: graphVersion(),
	}
}

// configured reports whether the resolver has everything it needs to actually
// fetch and store. When false, Resolve defers without any side effect.
func (mr *MediaResolver) configured() bool {
	return mr.token != "" && mr.bucket != "" && mr.store != nil
}

// Resolve attempts inbound media retrieval for a single parsed message,
// returning a MediaRecord describing the outcome. It NEVER returns an error:
// every failure mode is captured as a non-Stored MediaStatus so it can never
// fail the webhook. msg supplies the message Type; ref carries the media id /
// mime / filename extracted from the raw payload (see parseMediaRefs).
//
//   - non-media message            -> MediaStatusNone
//   - unsupported kind             -> MediaStatusOpenInApp
//   - token/bucket/store unset     -> MediaStatusDeferred (no network call)
//   - fetch+store succeeds         -> MediaStatusStored (StorageRef set)
//   - any retrieval failure        -> MediaStatusError (Detail set)
func (mr *MediaResolver) Resolve(ctx context.Context, ref mediaRef) MediaRecord {
	rec := MediaRecord{
		Kind:     ref.kind,
		MediaID:  ref.id,
		MimeType: ref.mimeType,
		Filename: ref.filename,
	}

	// A message with no media reference is simply nothing to do.
	if ref.kind == "" {
		rec.Status = MediaStatusNone
		return rec
	}

	// Kinds we can't pull via the media-download path need a human in the app.
	if !supportedMediaKinds[ref.kind] {
		rec.Status = MediaStatusOpenInApp
		rec.Detail = "unsupported media kind; open in WhatsApp app"
		return rec
	}

	// A supported kind that nonetheless carries no media id (e.g. a view-once
	// envelope that strips the id) can't be fetched — surface to a human.
	if ref.id == "" {
		rec.Status = MediaStatusOpenInApp
		rec.Detail = "no media id on message; open in WhatsApp app"
		return rec
	}

	// Inert without creds: defer with NO network call. The media id is
	// preserved so a later credentialed pass can resolve it.
	if !mr.configured() {
		rec.Status = MediaStatusDeferred
		rec.Detail = "media retrieval unconfigured (missing token/bucket); deferred"
		return rec
	}

	stored, err := mr.fetchAndStore(ctx, ref)
	if err != nil {
		rec.Status = MediaStatusError
		// Detail is a short reason; it carries no secret values or raw bytes.
		rec.Detail = "media retrieval failed: " + err.Error()
		return rec
	}

	rec.Status = MediaStatusStored
	rec.StorageRef = stored.ref
	rec.SizeBytes = stored.size
	if stored.mimeType != "" {
		rec.MimeType = stored.mimeType
	}
	return rec
}

// storedMedia is the internal result of a successful fetch+store.
type storedMedia struct {
	ref      string
	size     int64
	mimeType string
}

// graphMediaMeta is the Graph API response for GET /<version>/<media-id>. Only
// the fields we use are modeled; unknown fields are ignored.
type graphMediaMeta struct {
	URL      string `json:"url"`
	MimeType string `json:"mime_type"`
	FileSize int64  `json:"file_size"`
	ID       string `json:"id"`
}

// fetchAndStore performs the two-step Graph retrieval and copies the bytes into
// the durable store keyed by the wa media id.
//
//  1. GET graphBaseURL/<version>/<media-id> with Bearer -> { url, mime_type }
//     (url is a short-lived ~5-min lookaside link).
//  2. GET <url> WITH the same Bearer header -> the raw bytes (Meta requires the
//     token even on the lookaside host).
//  3. Stream the bytes into store.Put under a stable key derived from the id.
func (mr *MediaResolver) fetchAndStore(ctx context.Context, ref mediaRef) (storedMedia, error) {
	ctx, cancel := context.WithTimeout(ctx, mediaFetchTimeout)
	defer cancel()

	meta, err := mr.resolveMeta(ctx, ref.id)
	if err != nil {
		return storedMedia{}, err
	}
	if meta.URL == "" {
		return storedMedia{}, errors.New("graph metadata had no download url")
	}
	// SSRF / token-exfil guard: meta.URL comes from the Graph JSON (untrusted),
	// and we are about to GET it WITH the Bearer token. Only proceed if it is an
	// https URL on a Meta-owned host. A bad URL degrades to MediaStatusError, not
	// an authenticated request to an attacker-chosen host.
	if err := validateMediaURL(meta.URL); err != nil {
		return storedMedia{}, err
	}

	// Step 2: download the bytes from the lookaside URL WITH the Bearer header.
	resp, err := mr.client.Get(ctx, meta.URL, mr.token)
	if err != nil {
		return storedMedia{}, fmt.Errorf("download: %w", err)
	}
	defer drainClose(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return storedMedia{}, fmt.Errorf("download status %d", resp.StatusCode)
	}

	// Resolve the content type: prefer the Graph metadata mime, fall back to
	// the inbound message's reported mime, then to a safe generic default.
	contentType := firstNonEmpty(meta.MimeType, ref.mimeType, "application/octet-stream")

	// Bound the copied bytes so a hostile/corrupt response can't exhaust
	// memory or storage. We read one extra byte to detect an overflow.
	limited := io.LimitReader(resp.Body, maxMediaBytes+1)

	key := mediaStorageKey(ref.id, ref.filename)
	storeRef, size, err := mr.store.Put(ctx, key, contentType, limited)
	if err != nil {
		return storedMedia{}, fmt.Errorf("store: %w", err)
	}
	if size > maxMediaBytes {
		return storedMedia{}, fmt.Errorf("media exceeds %d byte cap", int64(maxMediaBytes))
	}

	return storedMedia{ref: storeRef, size: size, mimeType: meta.MimeType}, nil
}

// resolveMeta performs step 1: GET the media metadata to obtain the short-lived
// lookaside download URL.
func (mr *MediaResolver) resolveMeta(ctx context.Context, mediaID string) (graphMediaMeta, error) {
	metaURL := fmt.Sprintf("%s/%s/%s", graphBaseURL, mr.version, mediaID)
	resp, err := mr.client.Get(ctx, metaURL, mr.token)
	if err != nil {
		return graphMediaMeta{}, fmt.Errorf("resolve: %w", err)
	}
	defer drainClose(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return graphMediaMeta{}, fmt.Errorf("resolve status %d", resp.StatusCode)
	}
	// The metadata JSON is tiny; bound the read anyway.
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return graphMediaMeta{}, fmt.Errorf("resolve read: %w", err)
	}
	var meta graphMediaMeta
	if err := json.Unmarshal(body, &meta); err != nil {
		return graphMediaMeta{}, fmt.Errorf("resolve decode: %w", err)
	}
	return meta, nil
}

// mediaStorageKey builds a stable, collision-resistant object key from the wa
// media id (which is globally unique per attachment). When a filename is known
// it is appended so the stored object keeps a human-meaningful, extension-
// bearing name. The id is sanitized to a safe key segment.
func mediaStorageKey(mediaID, filename string) string {
	id := sanitizeKeySegment(mediaID)
	key := "whatsapp/media/" + id
	if name := sanitizeKeySegment(filename); name != "" {
		key += "/" + name
	}
	return key
}

// sanitizeKeySegment reduces an arbitrary string to a safe object-key segment:
// it keeps alphanumerics, dash, underscore, and dot, and replaces anything else
// with an underscore. Empty input yields empty output.
func sanitizeKeySegment(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return ""
	}
	var b strings.Builder
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
			b.WriteRune(r)
		case r == '-' || r == '_' || r == '.':
			b.WriteRune(r)
		default:
			b.WriteRune('_')
		}
	}
	return b.String()
}

// firstNonEmpty returns the first non-empty argument, or "" if all are empty.
func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if strings.TrimSpace(v) != "" {
			return v
		}
	}
	return ""
}

// drainClose drains and closes an HTTP body so the underlying connection can be
// reused, swallowing errors (best-effort cleanup on a read path).
func drainClose(rc io.ReadCloser) {
	if rc == nil {
		return
	}
	_, _ = io.Copy(io.Discard, rc)
	_ = rc.Close()
}

// -----------------------------------------------------------------------------
// mediaRef extraction — parse media ids straight from the raw Meta payload.
// -----------------------------------------------------------------------------

// mediaRef is the media descriptor extracted from a single inbound message: its
// kind, the Meta media id, and any sender-reported mime/filename. A message
// with no media yields the zero mediaRef (kind == "").
type mediaRef struct {
	messageID string
	kind      string
	id        string
	mimeType  string
	filename  string
}

// mediaPayload mirrors only the media-bearing slices of a Meta webhook body. It
// is intentionally separate from payload.go's metaPayload so this file adds to
// the package without modifying the existing parser. Unknown fields are ignored.
type mediaPayload struct {
	Entry []struct {
		Changes []struct {
			Value struct {
				Messages []mediaMessage `json:"messages"`
			} `json:"value"`
		} `json:"changes"`
	} `json:"entry"`
}

// mediaObject is the common shape of WhatsApp's media sub-objects (image, audio,
// video, document, voice, sticker). Each carries an "id"; documents also carry
// a "filename". "sha256" and "caption" exist on some kinds but are not needed.
type mediaObject struct {
	ID       string `json:"id"`
	MimeType string `json:"mime_type"`
	Filename string `json:"filename"`
}

// mediaMessage models a single inbound message with each possible media kind as
// an optional sub-object. Only the media-bearing fields are present; text is
// handled by the existing parser.
type mediaMessage struct {
	ID       string       `json:"id"`
	Type     string       `json:"type"`
	Image    *mediaObject `json:"image"`
	Audio    *mediaObject `json:"audio"`
	Video    *mediaObject `json:"video"`
	Document *mediaObject `json:"document"`
	Voice    *mediaObject `json:"voice"`
	Sticker  *mediaObject `json:"sticker"`
}

// mediaObjectFor returns the media sub-object for the message's declared type,
// or nil when the message is not a (modeled) media message.
func (m mediaMessage) mediaObjectFor() *mediaObject {
	switch m.Type {
	case "image":
		return m.Image
	case "audio":
		return m.Audio
	case "video":
		return m.Video
	case "document":
		return m.Document
	case "voice":
		return m.Voice
	case "sticker":
		return m.Sticker
	default:
		return nil
	}
}

// parseMediaRefs flattens every media-bearing inbound message in a raw Meta
// webhook body into a slice of mediaRef values, one per media message, in the
// same order parsePayload would yield them. Text/non-media messages are
// skipped. It returns an error only when the JSON itself is malformed, matching
// parsePayload's contract.
//
// This lets the handler line up a mediaRef with each InboundMessage by message
// id without the existing parser needing to know about media at all.
func parseMediaRefs(raw []byte) ([]mediaRef, error) {
	var p mediaPayload
	if err := json.Unmarshal(raw, &p); err != nil {
		return nil, err
	}
	var out []mediaRef
	for _, entry := range p.Entry {
		for _, change := range entry.Changes {
			for _, m := range change.Value.Messages {
				obj := m.mediaObjectFor()
				if obj == nil {
					// Not a modeled media message (text, location, etc.).
					continue
				}
				out = append(out, mediaRef{
					messageID: m.ID,
					kind:      m.Type,
					id:        obj.ID,
					mimeType:  obj.MimeType,
					filename:  obj.Filename,
				})
			}
		}
	}
	return out, nil
}

// -----------------------------------------------------------------------------
// HTTPGraphClient — the production GraphClient over net/http.
// -----------------------------------------------------------------------------

// HTTPGraphClient is the concrete GraphClient used in production. It performs
// authenticated GETs against the Meta Graph API and the lookaside media host,
// attaching the Bearer token. It does ONLY GETs: there is no method that could
// send a message.
type HTTPGraphClient struct {
	hc *http.Client
}

// NewHTTPGraphClient wraps an *http.Client as a GraphClient. When hc is nil it
// builds a hardened default whose CheckRedirect re-validates EVERY redirect hop
// against the Meta media-host allowlist (and https). This stops a lookaside 302
// from bouncing the Bearer-carrying request to an internal/attacker host (an SSRF
// the initial-URL check alone would miss). A blocked redirect surfaces as a Get
// error, which Resolve degrades to MediaStatusError — never a 500.
func NewHTTPGraphClient(hc *http.Client) *HTTPGraphClient {
	if hc == nil {
		hc = &http.Client{
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				if len(via) >= 10 {
					return errors.New("stopped after 10 redirects")
				}
				if req.URL.Scheme != "https" || !allowedMediaHost(req.URL.Hostname()) {
					return fmt.Errorf("blocked redirect to disallowed host %q", req.URL.Hostname())
				}
				return nil
			},
		}
	}
	return &HTTPGraphClient{hc: hc}
}

// Get performs an authenticated GET, attaching "Authorization: Bearer <bearer>".
// The caller owns closing resp.Body.
func (c *HTTPGraphClient) Get(ctx context.Context, url, bearer string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	return c.hc.Do(req)
}
