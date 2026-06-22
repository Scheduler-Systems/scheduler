// Package notifications implements the HTTP handlers for the user notification
// feed: list the actor's notifications and create one (system/seed path).
package notifications

import (
	"net/http"
	"strings"
	"time"

	"github.com/Scheduler-Systems/scheduler-api/internal/auth"
	"github.com/Scheduler-Systems/scheduler-api/internal/httputil"
	"github.com/Scheduler-Systems/scheduler-api/internal/idgen"
	"github.com/Scheduler-Systems/scheduler-api/internal/store"
)

func now() string { return time.Now().UTC().Format(time.RFC3339) }

// ListHandler handles GET /v1/tenants/{tenantId}/notifications — the actor's own
// notifications, newest first.
func ListHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		items := st.ListNotifications(params["tenantId"], actor.UserID)
		if items == nil {
			items = []store.Notification{}
		}
		httputil.WriteJSON(w, http.StatusOK, map[string]interface{}{"items": items})
	}
}

// CreateHandler handles POST /v1/tenants/{tenantId}/notifications — creates a
// notification for a recipient. Used by seeding/system events. Defaults the
// recipient to the actor when userId is omitted.
func CreateHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())

		var body struct {
			UserID    string `json:"userId"`
			Content   string `json:"content"`
			Type      string `json:"type"`
			ChatRefID string `json:"chatRefId"`
		}
		if err := httputil.ReadJSON(r, &body); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}

		userID := strings.TrimSpace(body.UserID)
		if userID == "" {
			userID = actor.UserID
		}
		// IDOR / notification-spoofing guard: a non-manager may only create a
		// notification addressed to THEMSELVES; only a manager/admin may target
		// another user (e.g. notifying their employees). Mirrors the userprofile
		// requireSelfOrAdmin boundary.
		if userID != actor.UserID && !auth.HasManagerBoundary(auth.Role(actor.Role)) {
			httputil.WriteJSON(w, http.StatusForbidden, map[string]string{
				"error": "forbidden", "message": "cannot create a notification for another user",
			})
			return
		}
		typ := strings.TrimSpace(body.Type)
		if typ == "" {
			typ = "SYSTEM"
		}

		n := store.Notification{
			ID:       "notif_" + idgen.RandID(),
			TenantID: params["tenantId"],
			UserID:   userID,
			// FromUser is server-derived (the actor), never trusted from the body —
			// prevents spoofing the sender.
			FromUser:  actor.UserID,
			Content:   strings.TrimSpace(body.Content),
			Type:      typ,
			ChatRefID: strings.TrimSpace(body.ChatRefID),
			IsRead:    false,
			CreatedAt: now(),
		}
		created := st.PutNotification(n)
		httputil.WriteJSON(w, http.StatusCreated, created)
	}
}
