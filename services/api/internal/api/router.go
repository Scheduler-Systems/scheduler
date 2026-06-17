package api

import (
	"net/http"
	"net/url"
	"strings"

	"github.com/Scheduler-Systems/scheduler-api/internal/auth"
	"github.com/Scheduler-Systems/scheduler-api/internal/employees"
	"github.com/Scheduler-Systems/scheduler-api/internal/health"
	"github.com/Scheduler-Systems/scheduler-api/internal/httputil"
	"github.com/Scheduler-Systems/scheduler-api/internal/schedgy"
	"github.com/Scheduler-Systems/scheduler-api/internal/schedules"
	"github.com/Scheduler-Systems/scheduler-api/internal/store"
	"github.com/Scheduler-Systems/scheduler-api/internal/webhooks/whatsapp"
)

// route is an internal matched-route descriptor.
type route struct {
	params      map[string]string
	managerOnly bool
	handler     http.HandlerFunc
}

// whatsappWebhookPath is the top-level, tenant-less path Meta calls for the
// WhatsApp Business Cloud API webhook. It deliberately lives OUTSIDE the
// /v1/tenants/{tenantId}/ tree because Meta's callers are unauthenticated from
// the tenant Bearer/role model's perspective — they authenticate only by the
// per-request HMAC signature, which the WhatsApp EventHandler verifies itself.
const whatsappWebhookPath = "/webhooks/whatsapp"

// NewHandler returns the root http.Handler for the scheduler-api.
//
// It wires together auth, rate-limiting, and route dispatch in the same order
// as the original Node.js handleRequest function.
//
// verifier verifies the Firebase ID token and is the sole authority for the
// actor's identity and role (issue #19). It must be non-nil.
func NewHandler(st store.Store, rl *RateLimiter, verifier auth.Verifier) http.Handler {
	// Wire the report-only WhatsApp webhook receiver once at construction,
	// mirroring how main.go wires the in-memory store. The default sink is an
	// append-only in-memory store + structured JSON log; an optional
	// internal-only Slack notify decorator is applied iff WHATSAPP_NOTIFY_SLACK
	// is explicitly enabled (it is OFF by default, and no Slack notifier is
	// wired here, so it stays inert until a deployment opts in). The receiver
	// has no send-to-customer path.
	waSink := whatsapp.MaybeSlackNotify(whatsapp.NewMemorySink(nil), nil)
	waVerify := whatsapp.VerifyHandler()
	waEvent := whatsapp.EventHandler(waSink)

	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Reject non-canonical paths before routing. Double slashes are
		// silently collapsed by splitPath, which could allow path-traversal
		// style ambiguity. Return 400 so callers fix their URLs explicitly.
		if strings.Contains(r.URL.Path, "//") {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid_path"})
			return
		}

		// Pre-auth branch: the WhatsApp webhook is unauthenticated by Meta and
		// MUST bypass the tenant Bearer/role middleware. It is handled here,
		// before Authenticate, because it has no tenantId and authenticates via
		// its own per-request HMAC check (POST) or shared verify token (GET).
		if r.URL.Path == whatsappWebhookPath {
			switch r.Method {
			case http.MethodGet:
				waVerify(w, r)
			case http.MethodPost:
				waEvent(w, r)
			default:
				WriteJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method_not_allowed"})
			}
			return
		}

		rt := matchRoute(r.Method, r.URL.Path, st)
		if rt == nil {
			WriteJSON(w, http.StatusNotFound, map[string]string{"error": "not_found"})
			return
		}

		tenantID := rt.params["tenantId"]

		// Order: auth → rate limit → role → handler.
		// Rate limiting is checked before role enforcement so that a
		// throttled tenant receives 429 rather than 403 when they are both
		// over the limit and lacking the required role — consistent with the
		// original Node.js handleRequest ordering.
		authRes := Authenticate(r, tenantID, verifier)
		if !authRes.OK {
			WriteJSON(w, authRes.Status, map[string]string{"error": authRes.Error})
			return
		}

		rateRes := rl.Check(authRes.Actor.TenantID)
		if !rateRes.OK {
			WriteJSON(w, http.StatusTooManyRequests, map[string]interface{}{
				"error":      "rate_limited",
				"retryAfter": rateRes.RetryAfter,
			})
			return
		}

		if rt.managerOnly && !HasManagerApprovalBoundary(authRes.Actor) {
			WriteJSON(w, http.StatusForbidden, map[string]string{"error": "manager_approval_required"})
			return
		}

		// Attach actor and route params to the request context so handlers can read them.
		ctx := WithActor(r.Context(), authRes.Actor)
		ctx = WithParams(ctx, rt.params)
		r = r.WithContext(ctx)

		rt.handler(w, r)
	})
}

// matchRoute maps (method, pathname) to a route descriptor using the same
// segment-based logic as matchRoute in src/app.mjs.
//
// All routes live under /v1/tenants/{tenantId}/.
func matchRoute(method, pathname string, st store.Store) *route {
	parts := splitPath(pathname)

	// All routes must start with /v1/tenants/{tenantId}/
	if len(parts) < 4 || parts[0] != "v1" || parts[1] != "tenants" || parts[2] == "" {
		return nil
	}

	tenantID := parts[2]
	p := map[string]string{"tenantId": tenantID}

	section := parts[3]
	depth := len(parts)

	switch section {

	// -------------------------------------------------------------------------
	// Schedule routes
	// -------------------------------------------------------------------------
	case "schedules":
		switch {

		// GET /schedules
		case method == http.MethodGet && depth == 4:
			return &route{params: p, handler: schedules.ListHandler(st)}

		// POST /schedules
		case method == http.MethodPost && depth == 4:
			return &route{params: p, managerOnly: true, handler: schedules.CreateHandler(st)}

		// GET /schedules/{id}
		case method == http.MethodGet && depth == 5:
			rp := copyWith(p, "scheduleId", parts[4])
			return &route{params: rp, handler: schedules.GetHandler(st)}

		// PATCH /schedules/{id}
		case method == http.MethodPatch && depth == 5:
			rp := copyWith(p, "scheduleId", parts[4])
			return &route{params: rp, managerOnly: true, handler: schedules.PatchHandler(st)}

		// PUT /schedules/{id}
		case method == http.MethodPut && depth == 5:
			rp := copyWith(p, "scheduleId", parts[4])
			return &route{params: rp, managerOnly: true, handler: schedules.PutHandler(st)}

		// DELETE /schedules/{id}
		case method == http.MethodDelete && depth == 5:
			rp := copyWith(p, "scheduleId", parts[4])
			return &route{params: rp, managerOnly: true, handler: schedules.DeleteHandler(st)}

		// POST /schedules/{id}/availability
		case method == http.MethodPost && depth == 6 && parts[5] == "availability":
			rp := copyWith(p, "scheduleId", parts[4])
			return &route{params: rp, handler: schedules.AvailabilityHandler(st)}

		// POST /schedules/{id}/drafts
		case method == http.MethodPost && depth == 6 && parts[5] == "drafts":
			rp := copyWith(p, "scheduleId", parts[4])
			return &route{params: rp, managerOnly: true, handler: schedules.DraftHandler(st)}

		// POST /schedules/{id}/publish
		case method == http.MethodPost && depth == 6 && parts[5] == "publish":
			rp := copyWith(p, "scheduleId", parts[4])
			return &route{params: rp, managerOnly: true, handler: schedules.PublishHandler(st)}

		// POST /schedules/{id}/requests
		case method == http.MethodPost && depth == 6 && parts[5] == "requests":
			rp := copyWith(p, "scheduleId", parts[4])
			return &route{params: rp, handler: schedules.RequestHandler(st)}

		// ---- Employees (embedded roster) ------------------------------------
		// All employee mutations are manager-gated at the router AND
		// membership-gated inside the handler (the schedule_acl analogue).

		// GET /schedules/{id}/employees
		case method == http.MethodGet && depth == 6 && parts[5] == "employees":
			rp := copyWith(p, "scheduleId", parts[4])
			return &route{params: rp, handler: employees.ListHandler(st)}

		// POST /schedules/{id}/employees
		case method == http.MethodPost && depth == 6 && parts[5] == "employees":
			rp := copyWith(p, "scheduleId", parts[4])
			return &route{params: rp, managerOnly: true, handler: employees.AddHandler(st)}

		// POST /schedules/{id}/employees:bulk
		case method == http.MethodPost && depth == 6 && parts[5] == "employees:bulk":
			rp := copyWith(p, "scheduleId", parts[4])
			return &route{params: rp, managerOnly: true, handler: employees.AddBulkHandler(st)}

		// GET  /schedules/{id}/employees/invitations
		case method == http.MethodGet && depth == 7 && parts[5] == "employees" && parts[6] == "invitations":
			rp := copyWith(p, "scheduleId", parts[4])
			return &route{params: rp, handler: employees.ListInvitationsHandler(st)}

		// POST /schedules/{id}/employees/invitations   (manager invites)
		case method == http.MethodPost && depth == 7 && parts[5] == "employees" && parts[6] == "invitations":
			rp := copyWith(p, "scheduleId", parts[4])
			return &route{params: rp, managerOnly: true, handler: employees.InviteHandler(st)}

		// POST /schedules/{id}/employees/invitations/{invitationId}/accept
		// (invitee responds — intentionally NOT manager-gated)
		case method == http.MethodPost && depth == 9 && parts[5] == "employees" &&
			parts[6] == "invitations" && parts[8] == "accept":
			rp := copyWith(p, "scheduleId", parts[4])
			rp = copyWith(rp, "invitationId", parts[7])
			return &route{params: rp, handler: employees.AcceptHandler(st)}

		// GET    /schedules/{id}/employees/{employeeEmail}
		case method == http.MethodGet && depth == 7 && parts[5] == "employees":
			rp := copyWith(p, "scheduleId", parts[4])
			rp = copyWith(rp, "employeeEmail", decodePathSegment(parts[6]))
			return &route{params: rp, handler: employees.GetHandler(st)}

		// DELETE /schedules/{id}/employees/{employeeEmail}
		case method == http.MethodDelete && depth == 7 && parts[5] == "employees":
			rp := copyWith(p, "scheduleId", parts[4])
			rp = copyWith(rp, "employeeEmail", decodePathSegment(parts[6]))
			return &route{params: rp, managerOnly: true, handler: employees.RemoveHandler(st)}
		}

	// -------------------------------------------------------------------------
	// Schedgy routes
	// -------------------------------------------------------------------------
	case "schedgy":
		switch {

		// POST /schedgy/approved-constraints:import
		case method == http.MethodPost && depth == 5 && parts[4] == "approved-constraints:import":
			return &route{params: p, managerOnly: true, handler: schedgy.ImportHandler(st)}

		// GET /schedgy/imports  (depth == 5, parts[4] == "imports")
		case method == http.MethodGet && depth == 5 && parts[4] == "imports":
			return &route{params: p, handler: schedgy.ListImportsHandler(st)}

		// GET /schedgy/imports/{importId}  (depth == 6)
		case method == http.MethodGet && depth == 6 && parts[4] == "imports":
			rp := copyWith(p, "importId", parts[5])
			return &route{params: rp, handler: schedgy.GetImportHandler(st)}
		}

	// -------------------------------------------------------------------------
	// Health routes
	// -------------------------------------------------------------------------
	case "healthz":
		if method == http.MethodGet && depth == 4 {
			return &route{params: p, handler: health.HealthzHandler()}
		}

	case "readyz":
		if method == http.MethodGet && depth == 4 {
			return &route{params: p, handler: health.ReadyzHandler()}
		}

	case "status":
		if method == http.MethodGet && depth == 4 {
			return &route{params: p, handler: health.StatusHandler()}
		}
	}

	return nil
}

// decodePathSegment percent-decodes a single path segment (e.g. an employee
// email like "bob%40acme.com"). On a decode error it returns the raw segment
// unchanged so a malformed segment simply fails to match a stored record rather
// than crashing the router.
func decodePathSegment(seg string) string {
	if decoded, err := url.PathUnescape(seg); err == nil {
		return decoded
	}
	return seg
}

// splitPath splits a URL path on "/" and discards empty segments (the leading
// slash produces one).
func splitPath(path string) []string {
	var parts []string
	for _, seg := range strings.Split(path, "/") {
		if seg != "" {
			parts = append(parts, seg)
		}
	}
	return parts
}

// copyWith returns a copy of src with an additional key/value pair.
func copyWith(src map[string]string, k, v string) map[string]string {
	dst := make(map[string]string, len(src)+1)
	for key, val := range src {
		dst[key] = val
	}
	dst[k] = v
	return dst
}
