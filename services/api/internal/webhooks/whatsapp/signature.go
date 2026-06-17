package whatsapp

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"strings"
)

// signaturePrefix is the scheme Meta prepends to the X-Hub-Signature-256 header
// value, e.g. "sha256=ab12...".
const signaturePrefix = "sha256="

// verifySignature reports whether header is a valid X-Hub-Signature-256 for the
// given raw body under appSecret.
//
// Meta computes the signature as:
//
//	"sha256=" + hex(HMAC_SHA256(rawBody, appSecret))
//
// The comparison is constant-time (hmac.Equal over the decoded bytes) to avoid
// leaking timing information about how many leading bytes matched. This adapts
// the idea from the Sentry Cloudflare Worker reference (crypto.subtle HMAC
// verify) to Go's crypto/hmac + crypto/sha256.
//
// It returns false for an empty/missing header, an empty app secret (so a
// misconfigured deployment fails CLOSED rather than accepting everything), a
// wrong scheme prefix, or non-hex content.
func verifySignature(rawBody []byte, header, appSecret string) bool {
	if appSecret == "" {
		// Fail closed: without a configured secret we cannot trust any body.
		return false
	}
	if !strings.HasPrefix(header, signaturePrefix) {
		return false
	}
	wantHex := strings.TrimPrefix(header, signaturePrefix)
	want, err := hex.DecodeString(wantHex)
	if err != nil {
		return false
	}

	mac := hmac.New(sha256.New, []byte(appSecret))
	mac.Write(rawBody)
	got := mac.Sum(nil)

	// hmac.Equal is constant-time and also length-safe.
	return hmac.Equal(got, want)
}
