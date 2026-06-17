// Package schedgy implements the HTTP handlers for the Schedgy integration
// endpoints: approved-constraints import, list imports, get import.
package schedgy

import (
	"net/http"
	"strconv"
	"time"

	"github.com/Scheduler-Systems/scheduler-api/internal/httputil"
	"github.com/Scheduler-Systems/scheduler-api/internal/idgen"
	"github.com/Scheduler-Systems/scheduler-api/internal/store"
)

// ImportHandler handles POST /v1/tenants/{tenantId}/schedgy/approved-constraints:import
func ImportHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())

		var body struct {
			SourceSystem        string                   `json:"sourceSystem"`
			ApprovedConstraints []map[string]interface{} `json:"approvedConstraints"`
			Metadata            map[string]interface{}   `json:"metadata"`
		}
		if err := httputil.ReadJSON(r, &body); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}

		if body.SourceSystem != "schedgy" {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "invalid_argument",
				"message": "sourceSystem must be schedgy",
			})
			return
		}

		if len(body.ApprovedConstraints) == 0 {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error":   "invalid_argument",
				"message": "approvedConstraints must be a non-empty array",
			})
			return
		}

		importID := "schedgy_import_" + idgen.RandID()
		approvalID := "approval_" + idgen.RandID()

		var importedConstraintIDs []string
		for _, item := range body.ApprovedConstraints {
			if constraint, ok := item["constraint"].(map[string]interface{}); ok {
				if id, ok := constraint["id"].(string); ok && id != "" {
					importedConstraintIDs = append(importedConstraintIDs, id)
				}
			}
		}
		if importedConstraintIDs == nil {
			importedConstraintIDs = []string{}
		}

		metadata := body.Metadata
		if metadata == nil {
			metadata = map[string]interface{}{}
		}

		importRecord := store.Import{
			ImportID:              importID,
			TenantID:              params["tenantId"],
			SourceSystem:          body.SourceSystem,
			ImportedConstraintIDs: importedConstraintIDs,
			TotalConstraints:      len(body.ApprovedConstraints),
			ImportedCount:         len(importedConstraintIDs),
			Metadata:              metadata,
			CreatedBy:             actor.UserID,
			CreatedAt:             time.Now().UnixMilli(),
		}

		approvalRecord := store.Approval{
			ID:                  approvalID,
			TenantID:            params["tenantId"],
			ImportID:            importID,
			State:               "pending",
			ConstraintsReviewed: len(importedConstraintIDs),
			CreatedAt:           time.Now().UTC().Format(time.RFC3339),
		}

		st.PutImport(importRecord)
		st.PutApproval(approvalRecord)

		httputil.WriteJSON(w, http.StatusAccepted, map[string]interface{}{
			"importId": importID,
			"tenantId": params["tenantId"],
			"importedConstraintIds": importedConstraintIDs,
			"approvalState": map[string]interface{}{
				"id":       approvalID,
				"tenantId": params["tenantId"],
				"state":    "pending",
			},
		})
	}
}

// GetImportHandler handles GET /v1/tenants/{tenantId}/schedgy/imports/{importId}
func GetImportHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		imp := st.GetImport(params["importId"])
		if imp == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "import_not_found"})
			return
		}
		if imp.TenantID != params["tenantId"] {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "import_not_found"})
			return
		}
		httputil.WriteJSON(w, http.StatusOK, imp)
	}
}

// ListImportsHandler handles GET /v1/tenants/{tenantId}/schedgy/imports
func ListImportsHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		limit := 50
		if v := r.URL.Query().Get("limit"); v != "" {
			if n, err := strconv.Atoi(v); err == nil && n > 0 {
				limit = n
			}
		}
		items := st.ListImports(params["tenantId"], limit)
		if items == nil {
			items = []store.Import{}
		}
		httputil.WriteJSON(w, http.StatusOK, map[string]interface{}{"items": items})
	}
}
