// Package employees implements the HTTP handlers for the employees domain:
// list/get/add/addBulk/remove plus the invite/accept workflow. Employees live
// embedded in a schedule (mirroring scheduler-web's schedules/{id}.employees[]
// array), so every handler is scoped to (tenantId, scheduleId) and gated on
// schedule membership — the Go-side analogue of the Firestore schedule_acl
// check that the IDOR fix introduced.
//
// This package is the first step of moving the employees domain off the web's
// Firestore-direct writes (lib/firestore-write.ts addEmployee / addEmployeesBulk
// / removeEmployee and lib/requests.ts createScheduleRequest /
// updateScheduleRequestStatus) and behind the server-authoritative Go API.
package employees

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

// requireScheduleMember writes the appropriate error response and returns false
// when the schedule does not exist (404) or the actor is not a member (403).
// On success it returns true and the caller may proceed.
//
// This is the IDOR-safe access check: passing tenant auth + manager role is NOT
// sufficient to mutate an arbitrary schedule's roster — the actor must be a
// member of THIS schedule (creator or linked employee), exactly as the
// Firestore schedule_acl rule enforces for the corresponding direct writes.
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

// employeeInput is the wire shape for a single employee on add/addBulk. It
// mirrors scheduler-web's EmployeeDetails (snake_case keys) so the API accepts
// the same JSON the web client already produces.
type employeeInput struct {
	Name  string `json:"employee_name"`
	Email string `json:"employee_email"`
	Phone string `json:"employee_phone"`
	Role  *struct {
		IsCreator bool `json:"is_creator"`
		IsAdmin   bool `json:"is_admin"`
		IsWorker  bool `json:"is_worker"`
	} `json:"role"`
	UserRef string `json:"user_ref"`
}

// toEmployee converts validated input into a store.Employee. A nil role
// defaults to a plain worker, matching the web default for invited staff.
func (in employeeInput) toEmployee() store.Employee {
	role := store.RoleStruct{IsWorker: true}
	if in.Role != nil {
		role = store.RoleStruct{
			IsCreator: in.Role.IsCreator,
			IsAdmin:   in.Role.IsAdmin,
			IsWorker:  in.Role.IsWorker,
		}
	}
	return store.Employee{
		Name:    strings.TrimSpace(in.Name),
		Email:   strings.TrimSpace(in.Email),
		Phone:   strings.TrimSpace(in.Phone),
		Role:    role,
		UserRef: strings.TrimSpace(in.UserRef),
	}
}

// ListHandler handles GET /v1/tenants/{tenantId}/schedules/{scheduleId}/employees
func ListHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}
		items := st.ListEmployees(params["tenantId"], params["scheduleId"])
		if items == nil {
			items = []store.Employee{}
		}
		httputil.WriteJSON(w, http.StatusOK, map[string]interface{}{"items": items})
	}
}

// GetHandler handles
// GET /v1/tenants/{tenantId}/schedules/{scheduleId}/employees/{employeeEmail}
//
// The employee is addressed by email (URL-decoded by the router). Email is the
// stable identity for an embedded employee record.
func GetHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}
		e := st.GetEmployee(params["tenantId"], params["scheduleId"], params["employeeEmail"])
		if e == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "employee_not_found"})
			return
		}
		httputil.WriteJSON(w, http.StatusOK, e)
	}
}

// AddHandler handles
// POST /v1/tenants/{tenantId}/schedules/{scheduleId}/employees
//
// Mirrors scheduler-web lib/firestore-write.ts addEmployee. Manager-only is
// enforced by the router; membership is enforced here. A duplicate email
// (case/space-insensitive) returns 409 so the client can show a clear message,
// rather than silently overwriting — the server is the source of truth for
// roster uniqueness, consistent with the schedules duplicate-name rule.
func AddHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}

		var in employeeInput
		if err := httputil.ReadJSON(r, &in); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}
		emp := in.toEmployee()
		if emp.Email == "" {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "invalid_argument",
				"message": "employee_email is required",
			})
			return
		}
		if existing := st.GetEmployee(params["tenantId"], params["scheduleId"], emp.Email); existing != nil {
			httputil.WriteJSON(w, http.StatusConflict, map[string]string{
				"error":   "employee_email_taken",
				"message": "An employee with this email already exists on the schedule",
			})
			return
		}

		stored, ok := st.PutEmployee(params["tenantId"], params["scheduleId"], emp)
		if !ok {
			// Schedule disappeared between the membership check and the write.
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "schedule_not_found"})
			return
		}
		httputil.WriteJSON(w, http.StatusCreated, stored)
	}
}

// AddBulkHandler handles
// POST /v1/tenants/{tenantId}/schedules/{scheduleId}/employees:bulk
//
// Mirrors scheduler-web lib/firestore-write.ts addEmployeesBulk (used by the
// CSV import). The whole batch is validated before any write so a single bad
// row rejects the request atomically and never half-applies. Duplicate emails
// (against existing roster OR within the batch) are reported as 409 with the
// offending emails, matching the single-add contract.
func AddBulkHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}

		var body struct {
			Employees []employeeInput `json:"employees"`
		}
		if err := httputil.ReadJSON(r, &body); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}
		if len(body.Employees) == 0 {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "invalid_argument",
				"message": "employees must be a non-empty array",
			})
			return
		}

		// Validate the whole batch first (all-or-nothing). Collect normalized
		// emails to catch both intra-batch and existing-roster duplicates
		// before mutating anything.
		emps := make([]store.Employee, 0, len(body.Employees))
		seen := make(map[string]bool, len(body.Employees))
		var conflicts []string
		for _, in := range body.Employees {
			emp := in.toEmployee()
			if emp.Email == "" {
				httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
					"error":   "invalid_argument",
					"message": "every employee requires employee_email",
				})
				return
			}
			norm := strings.ToLower(emp.Email)
			if seen[norm] {
				conflicts = append(conflicts, emp.Email)
				continue
			}
			seen[norm] = true
			if existing := st.GetEmployee(params["tenantId"], params["scheduleId"], emp.Email); existing != nil {
				conflicts = append(conflicts, emp.Email)
				continue
			}
			emps = append(emps, emp)
		}
		if len(conflicts) > 0 {
			httputil.WriteJSON(w, http.StatusConflict, map[string]interface{}{
				"error":     "employee_email_taken",
				"message":   "One or more employees already exist on the schedule or are duplicated in the batch",
				"conflicts": conflicts,
			})
			return
		}

		added := make([]store.Employee, 0, len(emps))
		for _, emp := range emps {
			stored, ok := st.PutEmployee(params["tenantId"], params["scheduleId"], emp)
			if !ok {
				httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "schedule_not_found"})
				return
			}
			added = append(added, stored)
		}
		httputil.WriteJSON(w, http.StatusCreated, map[string]interface{}{
			"items": added,
			"added": len(added),
		})
	}
}

// RemoveHandler handles
// DELETE /v1/tenants/{tenantId}/schedules/{scheduleId}/employees/{employeeEmail}
//
// Mirrors scheduler-web lib/firestore-write.ts removeEmployee.
func RemoveHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}
		if removed := st.RemoveEmployee(params["tenantId"], params["scheduleId"], params["employeeEmail"]); !removed {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "employee_not_found"})
			return
		}
		httputil.WriteJSON(w, http.StatusOK, map[string]interface{}{
			"success": true,
			"email":   params["employeeEmail"],
		})
	}
}

// -------------------------------------------------------------------------
// Invite / accept workflow (schedule_requests)
// -------------------------------------------------------------------------

// Status values mirror scheduler-web lib/requests-types.ts ScheduleRequestStatus
// verbatim, including the preserved Flutter typo "ADD_RQUEST_PENDING", so data
// written by this API round-trips with the existing iOS/Android/web clients.
const (
	statusAddPending   = "ADD_RQUEST_PENDING"
	statusJoinPending  = "JOIN_REQUEST_PENDING"
	statusAddAccepted  = "ADD_REQUEST_ACCEPTED"
	statusJoinAccepted = "JOIN_REQUEST_ACCEPTED"
	statusAddDeclined  = "ADD_REQUEST_DECLINED"
	statusJoinDeclined = "JOIN_REQUEST_DECLINED"
)

// InviteHandler handles
// POST /v1/tenants/{tenantId}/schedules/{scheduleId}/employees/invitations
//
// A manager (router-enforced) who is a member of the schedule invites an
// employee. Mirrors scheduler-web lib/requests.ts createScheduleRequest with
// is_add_request: true. The invitee is identified by email
// (to_user_identification); a known uid may be attached.
func InviteHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}

		var body struct {
			ToUserIdentification string `json:"toUserIdentification"`
			ToUserID             string `json:"toUserId"`
		}
		if err := httputil.ReadJSON(r, &body); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}
		ident := strings.TrimSpace(body.ToUserIdentification)
		if ident == "" {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "invalid_argument",
				"message": "toUserIdentification (invitee email) is required",
			})
			return
		}

		sched := st.GetSchedule(params["tenantId"], params["scheduleId"])
		inv := store.Invitation{
			ID:                   "invite_" + idgen.RandID(),
			TenantID:             params["tenantId"],
			ScheduleID:           params["scheduleId"],
			ScheduleName:         sched.Name,
			IsAddRequest:         true,
			IsJoinRequest:        false,
			FromUserID:           actor.UserID,
			ToUserID:             strings.TrimSpace(body.ToUserID),
			ToUserIdentification: ident,
			Status:               statusAddPending,
			CreatedAt:            now(),
		}
		st.PutInvitation(inv)
		httputil.WriteJSON(w, http.StatusCreated, inv)
	}
}

// AcceptHandler handles
// POST /v1/tenants/{tenantId}/schedules/{scheduleId}/employees/invitations/{invitationId}/accept
//
// The invited user accepts (or, with {"decline": true}, declines). Mirrors
// scheduler-web lib/requests.ts updateScheduleRequestStatus. On accept of an
// add-request, the invitee is materialized onto the schedule roster — the
// server performs the membership grant rather than trusting a client write.
//
// NOTE: accept/decline is intentionally NOT manager-gated (the router leaves it
// open) because the actor IS the invitee responding to their own invitation;
// the handler verifies the responder matches the invitation target.
func AcceptHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())

		if st.GetSchedule(params["tenantId"], params["scheduleId"]) == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "schedule_not_found"})
			return
		}
		inv := st.GetInvitation(params["tenantId"], params["invitationId"])
		if inv == nil || inv.ScheduleID != params["scheduleId"] {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "invitation_not_found"})
			return
		}

		// Only the invitee may respond. Match on uid when the invitation carries
		// one, otherwise fall back to the email identification — so an invite
		// sent before the invitee linked an account can still be accepted by the
		// user who later signs in with that email (uid supplied by the client as
		// the actor). An arbitrary third party cannot accept on their behalf.
		if !invitationTargetsActor(inv, actor) {
			httputil.WriteJSON(w, http.StatusForbidden, map[string]string{"error": "not_invitation_target"})
			return
		}

		// Reject double-processing: only a pending invitation can transition.
		if inv.Status != statusAddPending && inv.Status != statusJoinPending {
			httputil.WriteJSON(w, http.StatusConflict, map[string]string{
				"error":   "invitation_already_resolved",
				"message": "This invitation has already been accepted or declined",
			})
			return
		}

		var body struct {
			Decline bool `json:"decline"`
		}
		if err := httputil.ReadJSON(r, &body); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}

		inv.ReviewedBy = actor.UserID
		inv.ReviewedAt = now()

		if body.Decline {
			if inv.IsJoinRequest {
				inv.Status = statusJoinDeclined
			} else {
				inv.Status = statusAddDeclined
			}
			st.PutInvitation(*inv)
			httputil.WriteJSON(w, http.StatusOK, inv)
			return
		}

		// Accept: materialize membership. The new employee links to the
		// accepting actor's uid so future schedule_acl-style membership checks
		// pass for them.
		if inv.IsJoinRequest {
			inv.Status = statusJoinAccepted
		} else {
			inv.Status = statusAddAccepted
		}

		email := inv.ToUserIdentification
		if existing := st.GetEmployee(params["tenantId"], params["scheduleId"], email); existing == nil {
			emp := store.Employee{
				Email:   email,
				Role:    store.RoleStruct{IsWorker: true},
				UserRef: actor.UserID,
			}
			if _, ok := st.PutEmployee(params["tenantId"], params["scheduleId"], emp); !ok {
				httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "schedule_not_found"})
				return
			}
		} else if existing.UserRef == "" && actor.UserID != "" {
			// Link the existing roster row (added by email) to the accepting uid.
			existing.UserRef = actor.UserID
			st.PutEmployee(params["tenantId"], params["scheduleId"], *existing)
		}

		st.PutInvitation(*inv)
		httputil.WriteJSON(w, http.StatusOK, inv)
	}
}

// invitationTargetsActor reports whether the actor is the legitimate responder
// for an invitation. It requires a VERIFIABLE binding between the actor and the
// invitation and never accepts "any authenticated uid" — otherwise any logged-in
// user could hijack an email-only invitation by guessing/enumerating its id
// (IDOR / invitation hijacking).
//
//   - Bound-uid invitation (ToUserID set): only that exact uid may respond.
//   - Email-only invitation (no ToUserID): the actor must present a matching
//     email (gateway-injected on the verified actor, same trust level as the
//     uid). No actor email, or no invitation identification => cannot prove the
//     actor is the invitee => deny.
func invitationTargetsActor(inv *store.Invitation, actor httputil.Actor) bool {
	if inv.ToUserID != "" {
		return inv.ToUserID == actor.UserID
	}
	if actor.Email == "" || inv.ToUserIdentification == "" {
		return false
	}
	return normalizeEmail(actor.Email) == normalizeEmail(inv.ToUserIdentification)
}

// normalizeEmail trims and lower-cases an email so identification compares are
// case- and whitespace-insensitive (mirrors store.normalizeEmail).
func normalizeEmail(email string) string {
	return strings.ToLower(strings.TrimSpace(email))
}

// ListInvitationsHandler handles
// GET /v1/tenants/{tenantId}/schedules/{scheduleId}/employees/invitations
//
// Lists invitations for a schedule, newest first. Membership-gated.
func ListInvitationsHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		if !requireScheduleMember(w, st, params["tenantId"], params["scheduleId"], actor.UserID) {
			return
		}
		items := st.ListInvitationsForSchedule(params["tenantId"], params["scheduleId"])
		if items == nil {
			items = []store.Invitation{}
		}
		httputil.WriteJSON(w, http.StatusOK, map[string]interface{}{"items": items})
	}
}
