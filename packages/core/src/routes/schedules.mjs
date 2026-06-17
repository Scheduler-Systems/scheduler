import { authenticate, hasManagerApprovalBoundary, jsonResponse, readJson } from "../middleware/auth.mjs";

export function createScheduleRoutes() {
  return {
    matchRoute(method, parts, { store }) {
      const tenantId = parts[2];

      if (method === "GET" && parts.length === 4 && parts[3] === "schedules") {
        return {
          params: { tenantId },
          handler: async ({ params }) =>
            jsonResponse(200, { items: store.listSchedules(params.tenantId) }),
        };
      }

      if (method === "POST" && parts.length === 4 && parts[3] === "schedules") {
        return {
          managerOnly: true,
          params: { tenantId },
          handler: async ({ request, params, actor }) => {
            const body = await readJson(request);
            if (!body.name) {
              return jsonResponse(400, { error: "invalid_argument", message: "name is required" });
            }
            const schedule = {
              id: body.id ?? `schedule_${Date.now()}`,
              tenantId: params.tenantId,
              name: body.name,
              settings: body.settings,
              scheduleSettings: body.schedule_settings ?? {},
              employees: body.employees ?? [],
              status: body.status ?? "draft",
              createdBy: actor.userId,
              createdAt: new Date().toISOString(),
              updatedAt: new Date().toISOString(),
            };
            store.appendAuditLog({ tenantId: params.tenantId, action: "schedule_create", scheduleId: schedule.id, actor: actor.userId });
            return jsonResponse(201, store.putSchedule(schedule));
          },
        };
      }

      if (method === "GET" && parts.length === 5 && parts[3] === "schedules") {
        return {
          params: { tenantId, scheduleId: parts[4] },
          handler: async ({ params }) => {
            const schedule = store.getSchedule(params.tenantId, params.scheduleId);
            return schedule
              ? jsonResponse(200, schedule)
              : jsonResponse(404, { error: "schedule_not_found" });
          },
        };
      }

      if (method === "PATCH" && parts.length === 5 && parts[3] === "schedules") {
        return {
          managerOnly: true,
          params: { tenantId, scheduleId: parts[4] },
          handler: async ({ request, params, actor }) => {
            const schedule = store.getSchedule(params.tenantId, params.scheduleId);
            if (!schedule) return jsonResponse(404, { error: "schedule_not_found" });
            const body = await readJson(request);
            const updates = body.updates ?? body;
            const updated = { ...schedule, ...updates, updatedAt: new Date().toISOString() };
            store.appendAuditLog({ tenantId: params.tenantId, action: "schedule_update", scheduleId: params.scheduleId, actor: actor.userId });
            return jsonResponse(200, store.putSchedule(updated));
          },
        };
      }

      if (method === "PUT" && parts.length === 5 && parts[3] === "schedules") {
        return {
          managerOnly: true,
          params: { tenantId, scheduleId: parts[4] },
          handler: async ({ request, params, actor }) => {
            const schedule = store.getSchedule(params.tenantId, params.scheduleId);
            if (!schedule) return jsonResponse(404, { error: "schedule_not_found" });
            const body = await readJson(request);
            const updated = { ...schedule, ...body, updatedAt: new Date().toISOString() };
            store.appendAuditLog({ tenantId: params.tenantId, action: "schedule_update", scheduleId: params.scheduleId, actor: actor.userId });
            return jsonResponse(200, store.putSchedule(updated));
          },
        };
      }

      if (method === "DELETE" && parts.length === 5 && parts[3] === "schedules") {
        return {
          managerOnly: true,
          params: { tenantId, scheduleId: parts[4] },
          handler: async ({ params, actor }) => {
            const schedule = store.getSchedule(params.tenantId, params.scheduleId);
            if (!schedule) return jsonResponse(404, { error: "schedule_not_found" });
            store.deleteSchedule(params.tenantId, params.scheduleId);
            store.appendAuditLog({ tenantId: params.tenantId, action: "schedule_delete", scheduleId: params.scheduleId, actor: actor.userId });
            return jsonResponse(200, { success: true, id: params.scheduleId });
          },
        };
      }

      if (method === "POST" && parts.length === 6 && parts[3] === "schedules" && parts[5] === "availability") {
        return {
          params: { tenantId, scheduleId: parts[4] },
          handler: async ({ request, params }) => {
            const schedule = store.getSchedule(params.tenantId, params.scheduleId);
            if (!schedule) return jsonResponse(404, { error: "schedule_not_found" });
            const body = await readJson(request);
            return jsonResponse(202, {
              id: body.approvalId ?? `approval_${Date.now()}`,
              tenantId: params.tenantId,
              scheduleId: params.scheduleId,
              state: "pending",
            });
          },
        };
      }

      if (method === "POST" && parts.length === 6 && parts[3] === "schedules" && parts[5] === "drafts") {
        return {
          managerOnly: true,
          params: { tenantId, scheduleId: parts[4] },
          handler: async ({ params, actor }) => {
            const schedule = store.getSchedule(params.tenantId, params.scheduleId);
            if (!schedule) return jsonResponse(404, { error: "schedule_not_found" });
            const draft = {
              id: `draft_${Date.now()}`,
              tenantId: params.tenantId,
              scheduleId: params.scheduleId,
              shifts: [],
              createdAt: new Date().toISOString(),
              createdBy: actor.userId,
            };
            store.appendAuditLog({ tenantId: params.tenantId, action: "draft_create", scheduleId: params.scheduleId, actor: actor.userId });
            return jsonResponse(201, draft);
          },
        };
      }

      if (method === "POST" && parts.length === 6 && parts[3] === "schedules" && parts[5] === "publish") {
        return {
          managerOnly: true,
          params: { tenantId, scheduleId: parts[4] },
          handler: async ({ request, params, actor }) => {
            const body = await readJson(request);
            const schedule = store.getSchedule(params.tenantId, params.scheduleId);
            if (!schedule) return jsonResponse(404, { error: "schedule_not_found" });
            if (!body.draftId) return jsonResponse(400, { error: "bad_request", message: "draftId required" });
            const draft = store.getDraft(body.draftId);
            if (!draft) return jsonResponse(404, { error: "draft_not_found" });
            store.appendAuditLog({ tenantId: params.tenantId, action: "schedule_publish", scheduleId: params.scheduleId, actor: actor.userId });
            const updated = { ...schedule, status: "published", updatedAt: new Date().toISOString() };
            store.putSchedule(updated);
            return jsonResponse(200, {
              tenantId: params.tenantId,
              scheduleId: params.scheduleId,
              draftId: body.draftId,
              publishedAt: new Date().toISOString(),
            });
          },
        };
      }

      if (method === "POST" && parts.length === 6 && parts[3] === "schedules" && parts[5] === "requests") {
        return {
          params: { tenantId, scheduleId: parts[4] },
          handler: async ({ request, params, actor }) => {
            const schedule = store.getSchedule(params.tenantId, params.scheduleId);
            if (!schedule) return jsonResponse(404, { error: "schedule_not_found" });
            const body = await readJson(request);
            const shiftRequest = {
              id: body.id ?? `request_${Date.now()}`,
              tenantId: params.tenantId,
              scheduleId: params.scheduleId,
              requestedBy: actor.userId,
              type: body.type ?? "shift",
              state: "pending",
              createdAt: new Date().toISOString(),
            };
            store.putShiftRequest(shiftRequest);
            store.appendAuditLog({ tenantId: params.tenantId, action: "shift_request", scheduleId: params.scheduleId, requestId: shiftRequest.id, actor: actor.userId });
            return jsonResponse(202, shiftRequest);
          },
        };
      }

      return null;
    },
  };
}
