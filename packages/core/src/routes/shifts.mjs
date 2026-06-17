import { authenticate, hasManagerApprovalBoundary, jsonResponse, readJson } from "../middleware/auth.mjs";

export function createShiftRoutes() {
  return {
    matchRoute(method, parts, { store }) {
      const tenantId = parts[2];

      // GET /v1/tenants/{tenantId}/schedules/{scheduleId}/built
      if (method === "GET" && parts.length === 6 && parts[3] === "schedules" && parts[5] === "built") {
        return {
          params: { tenantId, scheduleId: parts[4] },
          handler: async ({ params }) =>
            jsonResponse(200, { items: store.listBuiltSchedules(params.tenantId, params.scheduleId) }),
        };
      }

      // POST /v1/tenants/{tenantId}/schedules/{scheduleId}/built
      if (method === "POST" && parts.length === 6 && parts[3] === "schedules" && parts[5] === "built") {
        return {
          managerOnly: true,
          params: { tenantId, scheduleId: parts[4] },
          handler: async ({ request, params, actor }) => {
            const body = await readJson(request);
            const built = {
              id: body.id ?? `built_${Date.now()}`,
              tenantId: params.tenantId,
              scheduleId: params.scheduleId,
              name: body.name,
              shifts: body.shifts ?? [],
              firstWeekday: body.firstWeekday ?? null,
              lastWeekday: body.lastWeekday ?? null,
              assignedBy: actor.userId,
              createdAt: new Date().toISOString(),
            };
            store.putBuiltSchedule(built);
            store.appendAuditLog({ tenantId: params.tenantId, action: "shift_build", scheduleId: params.scheduleId, builtId: built.id, actor: actor.userId });
            return jsonResponse(201, built);
          },
        };
      }

      // GET /v1/tenants/{tenantId}/schedules/{scheduleId}/built/{builtId}
      if (method === "GET" && parts.length === 7 && parts[3] === "schedules" && parts[5] === "built") {
        return {
          params: { tenantId, scheduleId: parts[4], builtId: parts[6] },
          handler: async ({ params }) => {
            const built = store.getBuiltSchedule(params.tenantId, params.scheduleId, params.builtId);
            return built
              ? jsonResponse(200, built)
              : jsonResponse(404, { error: "built_schedule_not_found" });
          },
        };
      }

      // POST /v1/tenants/{tenantId}/schedules/{scheduleId}/assign
      if (method === "POST" && parts.length === 6 && parts[3] === "schedules" && parts[5] === "assign") {
        return {
          managerOnly: true,
          params: { tenantId, scheduleId: parts[4] },
          handler: async ({ request, params, actor }) => {
            const body = await readJson(request);
            const assignments = {
              id: `assignment_${Date.now()}`,
              tenantId: params.tenantId,
              scheduleId: params.scheduleId,
              shifts: body.shifts ?? [],
              assignedTo: body.assignedTo ?? [],
              assignedBy: actor.userId,
              assignedAt: new Date().toISOString(),
            };
            store.appendAuditLog({ tenantId: params.tenantId, action: "shift_assign", scheduleId: params.scheduleId, actor: actor.userId });
            return jsonResponse(201, assignments);
          },
        };
      }

      // GET /v1/tenants/{tenantId}/requests
      if (method === "GET" && parts.length === 4 && parts[3] === "requests") {
        return {
          params: { tenantId },
          handler: async ({ request, params }) => {
            const url = new URL(request.url);
            const scheduleId = url.searchParams.get("scheduleId");
            const requests = scheduleId
              ? store.listShiftRequests(params.tenantId, scheduleId)
              : [];
            return jsonResponse(200, { items: requests });
          },
        };
      }

      return null;
    },
  };
}
