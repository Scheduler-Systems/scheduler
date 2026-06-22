// Package schedules implements the HTTP handlers for schedule CRUD and
// workflow operations (availability, drafts, publish, requests).
package schedules

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

// ListHandler handles GET /v1/tenants/{tenantId}/schedules
func ListHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		items := st.ListSchedules(params["tenantId"])
		if items == nil {
			items = []store.Schedule{}
		}
		httputil.WriteJSON(w, http.StatusOK, map[string]interface{}{"items": items})
	}
}

// CreateHandler handles POST /v1/tenants/{tenantId}/schedules
func CreateHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())

		var body struct {
			ID                string                 `json:"id"`
			Name              string                 `json:"name"`
			Settings          map[string]interface{} `json:"settings"`
			Status            string                 `json:"status"`
			CurrentPriorities []string               `json:"current_priorities"`
		}
		if err := httputil.ReadJSON(r, &body); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "bad_request",
				"message": err.Error(),
			})
			return
		}

		// Normalize the name once: trim surrounding whitespace so " Morning "
		// and "Morning" are treated identically here, in the duplicate check,
		// and in storage. This keeps the server's notion of a name consistent
		// with the iOS/Android/web clients.
		name := strings.TrimSpace(body.Name)
		if name == "" {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "invalid_argument",
				"message": "Schedule name is required",
			})
			return
		}

		// Duplicate name check — return 409 so the client can display a clear error.
		if existing := st.FindScheduleByName(params["tenantId"], name); existing != nil {
			httputil.WriteJSON(w, http.StatusConflict, map[string]string{
				"error":   "schedule_name_taken",
				"message": "A schedule with this name already exists",
			})
			return
		}

		id := body.ID
		if id == "" {
			id = "schedule_" + idgen.RandID()
		}
		status := body.Status
		if status == "" {
			status = "draft"
		}
		settings := body.Settings
		if settings == nil {
			settings = map[string]interface{}{}
		}

		// Capture timestamp once so CreatedAt and UpdatedAt are guaranteed
		// identical and cannot diverge on a nanosecond boundary.
		t := now()
		s := store.Schedule{
			ID:                id,
			TenantID:          params["tenantId"],
			Name:              name,
			Settings:          settings,
			Status:            status,
			CurrentPriorities: body.CurrentPriorities,
			CreatedBy:         actor.UserID,
			CreatedAt:         t,
			UpdatedAt:         t,
		}
		created := st.PutSchedule(s)
		httputil.WriteJSON(w, http.StatusCreated, created)
	}
}

// GetHandler handles GET /v1/tenants/{tenantId}/schedules/{scheduleId}
func GetHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		s := st.GetSchedule(params["tenantId"], params["scheduleId"])
		if s == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "schedule_not_found"})
			return
		}
		httputil.WriteJSON(w, http.StatusOK, s)
	}
}

// validateRename normalizes a new schedule name during an update and enforces
// the same duplicate-name rule as CreateHandler, so the server is the single
// source of truth for uniqueness across create AND update paths. It returns the
// trimmed name to store. ok is false when a response has already been written
// (empty name -> 400, or a different schedule already owns the name -> 409).
// Renaming a schedule to its own name (or a case/space variant of it) is allowed.
func validateRename(w http.ResponseWriter, st store.Store, tenantID, selfID, raw string) (string, bool) {
	name := strings.TrimSpace(raw)
	if name == "" {
		httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
			"error":   "invalid_argument",
			"message": "Schedule name is required",
		})
		return "", false
	}
	if existing := st.FindScheduleByName(tenantID, name); existing != nil && existing.ID != selfID {
		httputil.WriteJSON(w, http.StatusConflict, map[string]string{
			"error":   "schedule_name_taken",
			"message": "A schedule with this name already exists",
		})
		return "", false
	}
	return name, true
}

// PatchHandler handles PATCH /v1/tenants/{tenantId}/schedules/{scheduleId}
func PatchHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())

		var body struct {
			Updates map[string]interface{} `json:"updates"`
		}
		if err := httputil.ReadJSON(r, &body); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}
		if body.Updates == nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "invalid_argument",
				"message": "Updates are required",
			})
			return
		}

		existing := st.GetSchedule(params["tenantId"], params["scheduleId"])
		if existing == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "schedule_not_found"})
			return
		}

		// Apply only the allowed fields from updates.
		if v, ok := body.Updates["name"].(string); ok {
			name, valid := validateRename(w, st, params["tenantId"], existing.ID, v)
			if !valid {
				return
			}
			existing.Name = name
		}
		if v, ok := body.Updates["settings"].(map[string]interface{}); ok {
			existing.Settings = v
		}
		if v, ok := body.Updates["status"].(string); ok {
			existing.Status = v
		}
		// JSON arrays decode into []interface{}; coerce to []string.
		if v, ok := body.Updates["current_priorities"]; ok {
			existing.CurrentPriorities = toStringSlice(v)
		}

		updated := st.PutSchedule(*existing)
		httputil.WriteJSON(w, http.StatusOK, updated)
	}
}

// toStringSlice coerces a JSON-decoded value (typically []interface{} of strings,
// but also a native []string) into []string, skipping non-string elements.
func toStringSlice(v interface{}) []string {
	switch t := v.(type) {
	case []string:
		return t
	case []interface{}:
		out := make([]string, 0, len(t))
		for _, e := range t {
			if s, ok := e.(string); ok {
				out = append(out, s)
			}
		}
		return out
	default:
		return nil
	}
}

// PutHandler handles PUT /v1/tenants/{tenantId}/schedules/{scheduleId}
func PutHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())

		var body struct {
			Name              *string                `json:"name"`
			Settings          map[string]interface{} `json:"settings"`
			Status            *string                `json:"status"`
			CurrentPriorities *[]string              `json:"current_priorities"`
		}
		if err := httputil.ReadJSON(r, &body); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}

		existing := st.GetSchedule(params["tenantId"], params["scheduleId"])
		if existing == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "schedule_not_found"})
			return
		}

		if body.Name != nil {
			name, valid := validateRename(w, st, params["tenantId"], existing.ID, *body.Name)
			if !valid {
				return
			}
			existing.Name = name
		}
		if body.Settings != nil {
			existing.Settings = body.Settings
		}
		if body.Status != nil {
			existing.Status = *body.Status
		}
		if body.CurrentPriorities != nil {
			existing.CurrentPriorities = *body.CurrentPriorities
		}

		updated := st.PutSchedule(*existing)
		httputil.WriteJSON(w, http.StatusOK, updated)
	}
}

// DeleteHandler handles DELETE /v1/tenants/{tenantId}/schedules/{scheduleId}
func DeleteHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		existing := st.GetSchedule(params["tenantId"], params["scheduleId"])
		if existing == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "schedule_not_found"})
			return
		}
		st.DeleteSchedule(params["tenantId"], params["scheduleId"])
		httputil.WriteJSON(w, http.StatusOK, map[string]interface{}{
			"success": true,
			"id":      params["scheduleId"],
		})
	}
}

// AvailabilityHandler handles POST /v1/tenants/{tenantId}/schedules/{scheduleId}/availability
func AvailabilityHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())

		existing := st.GetSchedule(params["tenantId"], params["scheduleId"])
		if existing == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "schedule_not_found"})
			return
		}

		var body struct {
			ApprovalID   string                 `json:"approvalId"`
			Availability map[string]interface{} `json:"availability"`
		}
		if err := httputil.ReadJSON(r, &body); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}

		id := body.ApprovalID
		if id == "" {
			id = "approval_" + idgen.RandID()
		}
		avail := body.Availability
		if avail == nil {
			avail = map[string]interface{}{}
		}

		entry := store.Availability{
			ID:           id,
			TenantID:     params["tenantId"],
			ScheduleID:   params["scheduleId"],
			UserID:       actor.UserID,
			Availability: avail,
			State:        "pending",
			CreatedAt:    now(),
		}
		st.PutAvailability(entry)
		httputil.WriteJSON(w, http.StatusAccepted, entry)
	}
}

// DraftHandler handles POST /v1/tenants/{tenantId}/schedules/{scheduleId}/drafts
func DraftHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())

		existing := st.GetSchedule(params["tenantId"], params["scheduleId"])
		if existing == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "schedule_not_found"})
			return
		}

		var body struct {
			Shifts []interface{} `json:"shifts"`
		}
		if err := httputil.ReadJSON(r, &body); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}
		shifts := body.Shifts
		if shifts == nil {
			shifts = []interface{}{}
		}

		draft := store.Draft{
			ID:         "draft_" + idgen.RandID(),
			TenantID:   params["tenantId"],
			ScheduleID: params["scheduleId"],
			Shifts:     shifts,
			CreatedBy:  actor.UserID,
			CreatedAt:  now(),
		}
		st.PutDraft(draft)
		httputil.WriteJSON(w, http.StatusCreated, draft)
	}
}

// PublishHandler handles POST /v1/tenants/{tenantId}/schedules/{scheduleId}/publish
func PublishHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())

		var body struct {
			DraftID string `json:"draftId"`
		}
		if err := httputil.ReadJSON(r, &body); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}
		if body.DraftID == "" {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "invalid_argument",
				"message": "Draft ID is required",
			})
			return
		}

		draft := st.GetDraft(body.DraftID)
		if draft == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "draft_not_found"})
			return
		}
		if draft.TenantID != params["tenantId"] || draft.ScheduleID != params["scheduleId"] {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "draft_not_found"})
			return
		}

		schedule := st.GetSchedule(params["tenantId"], params["scheduleId"])
		if schedule == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "schedule_not_found"})
			return
		}

		publishedAt := now()
		schedule.Status = "published"
		schedule.PublishedAt = publishedAt
		schedule.PublishedBy = actor.UserID

		published := st.PutSchedule(*schedule)
		st.DeleteDraft(body.DraftID)

		httputil.WriteJSON(w, http.StatusOK, map[string]interface{}{
			"id":          published.ID,
			"tenantId":    published.TenantID,
			"scheduleId":  published.ID,
			"draftId":     body.DraftID,
			"publishedAt": published.PublishedAt,
		})
	}
}

// RequestHandler handles POST /v1/tenants/{tenantId}/schedules/{scheduleId}/requests
func RequestHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())

		existing := st.GetSchedule(params["tenantId"], params["scheduleId"])
		if existing == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "schedule_not_found"})
			return
		}

		var body struct {
			ID      string                 `json:"id"`
			Type    string                 `json:"type"`
			Details map[string]interface{} `json:"details"`
		}
		if err := httputil.ReadJSON(r, &body); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}

		id := body.ID
		if id == "" {
			id = "request_" + idgen.RandID()
		}
		reqType := body.Type
		if reqType == "" {
			reqType = "general"
		}
		details := body.Details
		if details == nil {
			details = map[string]interface{}{}
		}

		entry := store.Request{
			ID:         id,
			TenantID:   params["tenantId"],
			ScheduleID: params["scheduleId"],
			UserID:     actor.UserID,
			Type:       reqType,
			Details:    details,
			State:      "pending",
			CreatedAt:  now(),
		}
		st.PutRequest(entry)
		httputil.WriteJSON(w, http.StatusAccepted, entry)
	}
}
