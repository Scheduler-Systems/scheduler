import { authenticate, hasManagerApprovalBoundary, jsonResponse, readJson } from "../middleware/auth.mjs";

export function createSchedgyRoutes() {
  return {
    matchRoute(method, parts, { store }) {
      const tenantId = parts[2];

      if (method === "POST" && parts.length === 5 && parts[3] === "schedgy" && parts[4] === "approved-constraints:import") {
        return {
          managerOnly: true,
          params: { tenantId },
          handler: async ({ request, params, store, actor }) => {
            const body = await readJson(request);
            if (body.sourceSystem !== "schedgy") {
              return jsonResponse(400, { error: "invalid_argument", message: "sourceSystem must be schedgy" });
            }
            if (!body.approvedConstraints || body.approvedConstraints.length === 0) {
              return jsonResponse(400, { error: "invalid_argument", message: "approvedConstraints must not be empty" });
            }
            const importedConstraintIds = body.approvedConstraints.map((item) => item.constraint?.id ?? item.id).filter(Boolean);
            const result = {
              importId: `schedgy_import_${Date.now()}`,
              tenantId: params.tenantId,
              sourceSystem: body.sourceSystem,
              importedConstraintIds,
              importedCount: importedConstraintIds.length,
              sourceType: "approved-constraints",
              createdAt: Date.now(),
              updatedAt: Date.now(),
              approvalState: {
                id: `approval_${Date.now()}`,
                tenantId: params.tenantId,
                state: "pending",
              },
            };
            store.appendAuditLog({ tenantId: params.tenantId, action: "schedgy_import", importId: result.importId, actor: actor.userId });
            store.putImport(result);
            return jsonResponse(202, result);
          },
        };
      }

      if (method === "GET" && parts.length === 5 && parts[3] === "schedgy" && parts[4] === "imports") {
        return {
          params: { tenantId },
          handler: async ({ params }) => {
            const items = store.listImports(params.tenantId);
            return jsonResponse(200, { items });
          },
        };
      }

      if (method === "GET" && parts.length === 6 && parts[3] === "schedgy" && parts[4] === "imports") {
        return {
          params: { tenantId, importId: parts[5] },
          handler: async ({ params }) => {
            const imp = store.getImport(params.importId);
            if (!imp || imp.tenantId !== params.tenantId) {
              return jsonResponse(404, { error: "import_not_found" });
            }
            return jsonResponse(200, imp);
          },
        };
      }

      return null;
    },
  };
}
