package schedules

import (
	"net/http"

	"github.com/Scheduler-Systems/scheduler-api/internal/httputil"
	"github.com/Scheduler-Systems/scheduler-api/internal/idgen"
	"github.com/Scheduler-Systems/scheduler-api/internal/store"
)

// requireScheduleMember 404s when the schedule does not exist (or is in another
// tenant) and 403s when the actor is not a member of it. Mirrors the same guard
// in the employees/requests packages — the Go-side analogue of the Firestore
// schedule_acl membership check that the IDOR fix relies on.
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

// normalizeGrid coerces a nil grid to an empty 3-D slice and replaces any nil
// inner slices with empty ones, so a built schedule always serializes as a
// well-formed (never-null) grid for the native clients.
func normalizeGrid(g [][][]string) [][][]string {
	if g == nil {
		return [][][]string{}
	}
	for i := range g {
		if g[i] == nil {
			g[i] = [][]string{}
		}
		for j := range g[i] {
			if g[i][j] == nil {
				g[i][j] = []string{}
			}
		}
	}
	return g
}

// SaveBuiltHandler handles POST /schedules/{id}/built-schedules — persists a
// built shift grid (the published schedule). Manager-gated at the router AND
// membership-gated here. Identity (CreatedBy) is server-derived from the actor;
// the request body is the grid + period metadata only, never the author.
func SaveBuiltHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}

		var body struct {
			Grid                 [][][]string `json:"schedule"`
			FirstWeekday         string       `json:"first_weekday"`
			LastWeekday          string       `json:"last_weekday"`
			FirstWeekdayDateTime string       `json:"first_weekday_datetime"`
			LastWeekdayDateTime  string       `json:"last_weekday_datetime"`
			CurrentPriorities    []string     `json:"current_priorities"`
		}
		if err := httputil.ReadJSON(r, &body); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}
		priorities := body.CurrentPriorities
		if priorities == nil {
			priorities = []string{}
		}

		built := store.BuiltSchedule{
			ID:                   "built_" + idgen.RandID(),
			TenantID:             params["tenantId"],
			ScheduleID:           params["scheduleId"],
			Grid:                 normalizeGrid(body.Grid),
			FirstWeekday:         body.FirstWeekday,
			LastWeekday:          body.LastWeekday,
			FirstWeekdayDateTime: body.FirstWeekdayDateTime,
			LastWeekdayDateTime:  body.LastWeekdayDateTime,
			CurrentPriorities:    priorities,
			TimeCreated:          now(),
			CreatedBy:            actor.UserID, // server-derived; never trusted from the body.
		}
		stored := st.PutBuiltSchedule(built)
		httputil.WriteJSON(w, http.StatusCreated, stored)
	}
}

// ListBuiltHandler handles GET /schedules/{id}/built-schedules — the built
// schedules for a schedule, newest first. Any schedule member may read.
func ListBuiltHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}
		items := st.ListBuiltSchedulesForSchedule(params["tenantId"], params["scheduleId"])
		if items == nil {
			items = []store.BuiltSchedule{}
		}
		httputil.WriteJSON(w, http.StatusOK, map[string]interface{}{"items": items})
	}
}

// LatestBuiltHandler handles GET /schedules/{id}/built-schedules/latest — the
// most recently built grid (what export-shifts / share-pdf read). 404 if none.
func LatestBuiltHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}
		latest := st.GetLatestBuiltSchedule(params["tenantId"], params["scheduleId"])
		if latest == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "built_schedule_not_found"})
			return
		}
		httputil.WriteJSON(w, http.StatusOK, latest)
	}
}

// GetBuiltHandler handles GET /schedules/{id}/built-schedules/{builtId}.
func GetBuiltHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}
		b := st.GetBuiltSchedule(params["tenantId"], params["builtId"])
		// Scope to the path schedule so a built id from another schedule 404s.
		if b == nil || b.ScheduleID != params["scheduleId"] {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "built_schedule_not_found"})
			return
		}
		httputil.WriteJSON(w, http.StatusOK, b)
	}
}
