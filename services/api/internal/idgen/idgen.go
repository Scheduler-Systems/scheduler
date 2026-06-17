// Package idgen provides cryptographically random ID generation.
// It is intentionally small and dependency-free so that any handler
// package can import it without creating import cycles.
package idgen

import (
	"crypto/rand"
	"encoding/hex"
)

// RandID returns a 16-character lowercase hex string (8 random bytes).
// It uses crypto/rand so IDs are unique under concurrent requests, unlike
// a millisecond timestamp which collides when two goroutines call it within
// the same millisecond.
func RandID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}
