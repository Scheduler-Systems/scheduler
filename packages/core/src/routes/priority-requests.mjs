import { authenticate, hasManagerApprovalBoundary, jsonResponse, readJson } from "../middleware/auth.mjs";

export function createPriorityRequestRoutes() {
  return {
    matchRoute(method, parts, { store }) {
      const tenantId = parts[2];

      // POST /v1/tenants/{tenantId}/priority-requests
      if (method === "POST" && parts.length === 4 && parts[3] === "priority-requests") {
        return {
          params: { tenantId },
          handler: async ({ request, params, actor }) => {
            const body = await readJson(request);
            const priorityRequest = {
              id: body.id ?? `priority_${Date.now()}`,
              tenantId: params.tenantId,
              scheduleId: body.scheduleId,
              requestedBy: actor.userId,
              type: body.type ?? "priority_request",
              priority: body.priority ?? "normal",
              reason: body.reason ?? "",
              requestedShifts: body.requestedShifts ?? [],
              state: "pending",
              createdAt: new Date().toISOString(),
            };
            store.putShiftRequest(priorityRequest);
            store.appendAuditLog({ tenantId: params.tenantId, action: "priority_request", requestId: priorityRequest.id, actor: actor.userId });
            return jsonResponse(202, priorityRequest);
          },
        };
      }

      // GET /v1/tenants/{tenantId}/priority-requests
      if (method === "GET" && parts.length === 4 && parts[3] === "priority-requests") {
        return {
          params: { tenantId },
          handler: async ({ request, params }) => {
            const url = new URL(request.url);
            const scheduleId = url.searchParams.get("scheduleId");
            const requests = scheduleId
              ? store.listShiftRequests(params.tenantId, scheduleId).filter((r) => r.type === "priority_request")
              : [];
            return jsonResponse(200, { items: requests });
          },
        };
      }

      // PATCH /v1/tenants/{tenantId}/priority-requests/{requestId}
      if (method === "PATCH" && parts.length === 5 && parts[3] === "priority-requests") {
        return {
          managerOnly: true,
          params: { tenantId, requestId: parts[4] },
          handler: async ({ request, params, actor }) => {
            const body = await readJson(request);
            const existing = store.getShiftRequest(params.tenantId, params.requestId);
            if (!existing) return jsonResponse(404, { error: "request_not_found" });
            const updated = {
              ...existing,
              state: body.state ?? existing.state,
              reviewedBy: actor.userId,
              reviewedAt: new Date().toISOString(),
            };
            store.putShiftRequest(updated);
            store.appendAuditLog({ tenantId: params.tenantId, action: "priority_request_review", requestId: params.requestId, state: updated.state, actor: actor.userId });
            return jsonResponse(200, updated);
          },
        };
      }

      return null;
    },
  };
}
