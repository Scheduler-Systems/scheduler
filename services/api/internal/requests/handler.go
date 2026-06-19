// Package requests implements the HTTP handlers for the requests domain:
// shift-swap requests (built_schedules/{bid}/shift_requests) and
// schedule-change requests (scheduleChangeRequest). It is the second domain
// (P1) of moving scheduler-web off its Firestore-direct writes and behind the
// server-authoritative Go API, mirroring the employees domain pattern.
//
// Web entry points being replaced (scheduler-web lib/requests.ts):
//   - createShiftRequest / updateShiftRequestStatus / deleteShiftRequest
//   - createScheduleChangeRequest / updateScheduleChangeRequestStatus
//
// Every handler is scoped to (tenantId, scheduleId) and gated on schedule
// membership — the Go-side analogue of the Firestore schedule_acl check the
// IDOR fix introduced. Within that:
//   - the REQUESTER creates (POST is open to any member, e.g. an employee);
//   - the MANAGER approves/rejects (status transitions are router managerOnly);
//   - the AUTHOR may delete their own request only while it is still PENDING.
//
// Status strings mirror scheduler-web lib/requests-types.ts VERBATIM, including
// the Flutter typo "REJECETED", so data written here round-trips with the
// existing iOS/Android/web clients.
package requests

import (
	"net/http"
	"strings"
	"time"

	"github.com/Scheduler-Systems/scheduler-api/internal/httputil"
	"github.com/Scheduler-Systems/scheduler-api/internal/idgen"
	"github.com/Scheduler-Systems/scheduler-api/internal/store"
)

// now returns the current UTC time formatted as RFC3339.
func now() string {
	return time.Now().UTC().Format(time.RFC3339)
}

// ShiftRequestStatus values mirror scheduler-web lib/requests-types.ts
// ShiftRequestStatus verbatim — including the preserved Flutter typo
// "REJECETED" (a C/E metathesis) — so data round-trips with the clients.
const (
	shiftStatusPending  = "PENDING"
	shiftStatusAccepted = "ACCEPTED"
	shiftStatusRejected = "REJECETED" // Flutter typo, preserved on purpose.
)

// ScheduleChangeRequest status values. Flutter uses a free-text string here
// (not a typed enum): "sent" on create, "accepted"/"declined" on review.
const (
	changeStatusSent     = "sent"
	changeStatusAccepted = "accepted"
	changeStatusDeclined = "declined"
)

// requireScheduleMember writes the appropriate error response and returns false
// when the schedule does not exist (404 schedule_not_found) or the actor is not
// a member (403 not_a_schedule_member). On success it returns true.
//
// This is the IDOR-safe access check: passing tenant auth + a role is NOT
// sufficient to read or mutate an arbitrary schedule's requests — the actor
// must be a member of THIS schedule, exactly as the Firestore schedule_acl rule
// enforces for the corresponding direct writes. The schedule-existence check
// runs FIRST so a non-existent schedule is a 404 (not a membership leak).
func requireScheduleMember(w http.ResponseWriter, st store.Store, tenantID, scheduleID, userID string) bool {
	if st.GetSchedule(tenantID, scheduleID) == nil {
		httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "schedule_not_found"})
		return false
	}
	if !st.IsScheduleMember(tenantID, scheduleID, userID) {
		httputil.WriteJSON(w, http.StatusForbidden, map[string]string{"error": "not_a_schedule_member"})
		return false
	}
	return true
}

// =========================================================================
// Shift-swap requests
// =========================================================================

// shiftRequestInput is the wire shape for creating a shift-swap request. It
// mirrors scheduler-web's CreateShiftRequestInput (camelCase request body) so
// the API accepts what the web client already produces.
type shiftRequestInput struct {
	BuiltScheduleID   string `json:"builtScheduleId"`
	ShiftToChangeFrom string `json:"shiftToChangeFrom"`
	ShiftToChangeTo   string `json:"shiftToChangeTo"`
}

// ListShiftRequestsHandler handles
// GET /v1/tenants/{tenantId}/schedules/{scheduleId}/shift-requests
func ListShiftRequestsHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}
		items := st.ListShiftRequestsForSchedule(params["tenantId"], params["scheduleId"])
		if items == nil {
			items = []store.ShiftRequest{}
		}
		httputil.WriteJSON(w, http.StatusOK, map[string]interface{}{"items": items})
	}
}

// GetShiftRequestHandler handles
// GET /v1/tenants/{tenantId}/schedules/{scheduleId}/shift-requests/{requestId}
func GetShiftRequestHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}
		req := st.GetShiftRequest(params["tenantId"], params["requestId"])
		if req == nil || req.ScheduleID != params["scheduleId"] {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "shift_request_not_found"})
			return
		}
		httputil.WriteJSON(w, http.StatusOK, req)
	}
}

// CreateShiftRequestHandler handles
// POST /v1/tenants/{tenantId}/schedules/{scheduleId}/shift-requests
//
// Mirrors scheduler-web lib/requests.ts createShiftRequest. The REQUESTER (any
// schedule member, typically the employee who owns the shift) creates the
// request; it starts in status PENDING. The requesting_employee uid is taken
// from the authenticated actor, never trusted from the body, so a caller cannot
// forge a request on someone else's behalf. NOT manager-gated at the router —
// employees must be able to ask.
func CreateShiftRequestHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}

		var in shiftRequestInput
		if err := httputil.ReadJSON(r, &in); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}
		built := strings.TrimSpace(in.BuiltScheduleID)
		if built == "" {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "invalid_argument",
				"message": "builtScheduleId is required",
			})
			return
		}

		req := store.ShiftRequest{
			ID:                 "shiftreq_" + idgen.RandID(),
			TenantID:           params["tenantId"],
			ScheduleID:         params["scheduleId"],
			BuiltScheduleID:    built,
			RequestingEmployee: actor.UserID, // server-set; never trusted from the body.
			ShiftToChangeFrom:  strings.TrimSpace(in.ShiftToChangeFrom),
			ShiftToChangeTo:    strings.TrimSpace(in.ShiftToChangeTo),
			BuiltScheduleRef:   built,
			Status:             shiftStatusPending,
			CreatedAt:          now(),
		}
		stored := st.PutShiftRequest(req)
		httputil.WriteJSON(w, http.StatusCreated, stored)
	}
}

// shiftStatusUpdateInput is the wire shape for a shift-request status change.
type shiftStatusUpdateInput struct {
	Status string `json:"status"`
}

// validShiftTransitionStatus reports whether s is a permitted target status for
// a manager review (accept/reject). PENDING is the initial state and not a
// valid manual target.
func validShiftTransitionStatus(s string) bool {
	return s == shiftStatusAccepted || s == shiftStatusRejected
}

// UpdateShiftRequestStatusHandler handles
// PATCH /v1/tenants/{tenantId}/schedules/{scheduleId}/shift-requests/{requestId}
//
// Mirrors scheduler-web lib/requests.ts updateShiftRequestStatus. Router
// managerOnly gates this so only a manager can approve/reject; membership is
// enforced here too. Only a PENDING request can be transitioned, and only to
// ACCEPTED or REJECETED (typo preserved). The reviewer uid + timestamp are
// recorded for audit.
func UpdateShiftRequestStatusHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}

		req := st.GetShiftRequest(params["tenantId"], params["requestId"])
		if req == nil || req.ScheduleID != params["scheduleId"] {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "shift_request_not_found"})
			return
		}

		var in shiftStatusUpdateInput
		if err := httputil.ReadJSON(r, &in); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}
		status := strings.TrimSpace(in.Status)
		if !validShiftTransitionStatus(status) {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "invalid_status",
				"message": "status must be ACCEPTED or REJECETED",
			})
			return
		}
		if req.Status != shiftStatusPending {
			httputil.WriteJSON(w, http.StatusConflict, map[string]string{
				"error":   "shift_request_already_resolved",
				"message": "Only a PENDING shift request can be accepted or rejected",
			})
			return
		}

		req.Status = status
		req.ReviewerUID = actor.UserID
		req.ReviewedAt = now()
		stored := st.PutShiftRequest(*req)
		httputil.WriteJSON(w, http.StatusOK, stored)
	}
}

// DeleteShiftRequestHandler handles
// DELETE /v1/tenants/{tenantId}/schedules/{scheduleId}/shift-requests/{requestId}
//
// Mirrors scheduler-web lib/requests.ts deleteShiftRequest, which only permits
// deletion while the request is still PENDING (once reviewed, deletion is
// destructive of audit trail). NOT router managerOnly — the AUTHOR deletes
// their own pending request — so the handler verifies the actor is the
// requesting_employee. A non-author (even a manager) gets 403.
func DeleteShiftRequestHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}

		req := st.GetShiftRequest(params["tenantId"], params["requestId"])
		if req == nil || req.ScheduleID != params["scheduleId"] {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "shift_request_not_found"})
			return
		}
		// Only the author may delete their own request.
		if actor.UserID == "" || req.RequestingEmployee != actor.UserID {
			httputil.WriteJSON(w, http.StatusForbidden, map[string]string{"error": "not_request_author"})
			return
		}
		// Only a still-pending request may be deleted.
		if req.Status != shiftStatusPending {
			httputil.WriteJSON(w, http.StatusConflict, map[string]string{
				"error":   "shift_request_not_pending",
				"message": "Only a PENDING shift request may be deleted",
			})
			return
		}

		if !st.DeleteShiftRequest(params["tenantId"], params["requestId"]) {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "shift_request_not_found"})
			return
		}
		httputil.WriteJSON(w, http.StatusOK, map[string]interface{}{
			"success": true,
			"id":      params["requestId"],
		})
	}
}

// =========================================================================
// Schedule-change requests
// =========================================================================

// changeRequestInput is the wire shape for creating a schedule-change request.
// It mirrors scheduler-web's CreateScheduleChangeRequestInput (camelCase body).
type changeRequestInput struct {
	Reason   string `json:"reason"`
	DateTime string `json:"dateTime"`
	Status   string `json:"status"`
}

// ListChangeRequestsHandler handles
// GET /v1/tenants/{tenantId}/schedules/{scheduleId}/change-requests
func ListChangeRequestsHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}
		items := st.ListScheduleChangeRequestsForSchedule(params["tenantId"], params["scheduleId"])
		if items == nil {
			items = []store.ScheduleChangeRequest{}
		}
		httputil.WriteJSON(w, http.StatusOK, map[string]interface{}{"items": items})
	}
}

// GetChangeRequestHandler handles
// GET /v1/tenants/{tenantId}/schedules/{scheduleId}/change-requests/{requestId}
func GetChangeRequestHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}
		req := st.GetScheduleChangeRequest(params["tenantId"], params["requestId"])
		if req == nil || req.ScheduleID != params["scheduleId"] {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "change_request_not_found"})
			return
		}
		httputil.WriteJSON(w, http.StatusOK, req)
	}
}

// CreateChangeRequestHandler handles
// POST /v1/tenants/{tenantId}/schedules/{scheduleId}/change-requests
//
// Mirrors scheduler-web lib/requests.ts createScheduleChangeRequest. The
// REQUESTER (any schedule member) creates the request; it starts in status
// "sent" (matching Flutter's shift_change_requests_widget.dart). The userId is
// taken from the authenticated actor, never trusted from the body. NOT
// manager-gated at the router.
func CreateChangeRequestHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}

		var in changeRequestInput
		if err := httputil.ReadJSON(r, &in); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}
		reason := strings.TrimSpace(in.Reason)
		if reason == "" {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "invalid_argument",
				"message": "reason is required",
			})
			return
		}
		// Default status to "sent" (Flutter create default); honour an explicit
		// value only when it is "sent" — a creator cannot self-approve.
		status := changeStatusSent
		if s := strings.TrimSpace(in.Status); s != "" && s != changeStatusSent {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "invalid_status",
				"message": `status on create must be "sent" (or omitted)`,
			})
			return
		}

		req := store.ScheduleChangeRequest{
			ID:         "changereq_" + idgen.RandID(),
			TenantID:   params["tenantId"],
			ScheduleID: params["scheduleId"],
			DateTime:   strings.TrimSpace(in.DateTime),
			Reason:     reason,
			UserID:     actor.UserID, // server-set; never trusted from the body.
			Status:     status,
			CreatedAt:  now(),
		}
		stored := st.PutScheduleChangeRequest(req)
		httputil.WriteJSON(w, http.StatusCreated, stored)
	}
}

// changeStatusUpdateInput is the wire shape for a change-request status change.
type changeStatusUpdateInput struct {
	Status string `json:"status"`
}

// validChangeTransitionStatus reports whether s is a permitted target status
// for a manager review. "sent" is the initial state, not a valid manual target.
func validChangeTransitionStatus(s string) bool {
	return s == changeStatusAccepted || s == changeStatusDeclined
}

// UpdateChangeRequestStatusHandler handles
// PATCH /v1/tenants/{tenantId}/schedules/{scheduleId}/change-requests/{requestId}
//
// Mirrors scheduler-web lib/requests.ts updateScheduleChangeRequestStatus.
// Router managerOnly gates this so only a manager can approve/decline;
// membership is enforced here too. Only a "sent" request can transition, and
// only to "accepted" or "declined". The reviewer uid + resolved timestamp are
// recorded for audit (the resolved_at write is what Flutter's Cloud Function
// keys FCM off).
func UpdateChangeRequestStatusHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}

		req := st.GetScheduleChangeRequest(params["tenantId"], params["requestId"])
		if req == nil || req.ScheduleID != params["scheduleId"] {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "change_request_not_found"})
			return
		}

		var in changeStatusUpdateInput
		if err := httputil.ReadJSON(r, &in); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}
		status := strings.TrimSpace(in.Status)
		if !validChangeTransitionStatus(status) {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "invalid_status",
				"message": `status must be "accepted" or "declined"`,
			})
			return
		}
		if req.Status != changeStatusSent {
			httputil.WriteJSON(w, http.StatusConflict, map[string]string{
				"error":   "change_request_already_resolved",
				"message": `Only a "sent" schedule-change request can be accepted or declined`,
			})
			return
		}

		req.Status = status
		req.ReviewerUID = actor.UserID
		req.ResolvedAt = now()
		stored := st.PutScheduleChangeRequest(*req)
		httputil.WriteJSON(w, http.StatusOK, stored)
	}
}
