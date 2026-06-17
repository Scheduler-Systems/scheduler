package api

import (
	"sync"
	"time"
)

// RateLimiter is a per-tenant in-memory sliding-window rate limiter.
// It mirrors createMemoryRateLimit in src/app.mjs.
type RateLimiter struct {
	mu           sync.Mutex
	maxPerMinute int
	buckets      map[string]*rateBucket
}

type rateBucket struct {
	startedAt time.Time
	count     int
}

// RateResult is returned by Check.
type RateResult struct {
	OK         bool
	RetryAfter int // seconds until the window resets
}

// NewRateLimiter creates a new RateLimiter with the given per-tenant per-minute
// request cap.
func NewRateLimiter(maxPerMinute int) *RateLimiter {
	return &RateLimiter{
		maxPerMinute: maxPerMinute,
		buckets:      make(map[string]*rateBucket),
	}
}

// Check increments the counter for tenantID and returns whether the request
// is within the allowed rate.
func (rl *RateLimiter) Check(tenantID string) RateResult {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	now := time.Now()
	window := time.Minute

	b, ok := rl.buckets[tenantID]
	if !ok || now.Sub(b.startedAt) >= window {
		b = &rateBucket{startedAt: now, count: 0}
		rl.buckets[tenantID] = b
	}

	b.count++

	if b.count > rl.maxPerMinute {
		retryAfter := int(b.startedAt.Add(window).Sub(now).Seconds()) + 1
		if retryAfter < 1 {
			retryAfter = 1
		}
		return RateResult{OK: false, RetryAfter: retryAfter}
	}

	return RateResult{OK: true}
}
