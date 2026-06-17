package auth

import (
	"strconv"
	"strings"
	"time"
)

// maxAge parses the max-age directive (seconds) from a Cache-Control header
// value. Returns (0, false) when absent or unparsable.
func maxAge(cacheControl string) (time.Duration, bool) {
	for _, part := range strings.Split(cacheControl, ",") {
		part = strings.TrimSpace(part)
		if !strings.HasPrefix(part, "max-age=") {
			continue
		}
		secs, err := strconv.Atoi(strings.TrimPrefix(part, "max-age="))
		if err != nil || secs < 0 {
			return 0, false
		}
		return time.Duration(secs) * time.Second, true
	}
	return 0, false
}
