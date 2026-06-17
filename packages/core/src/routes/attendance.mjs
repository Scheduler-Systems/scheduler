import { jsonResponse, readJson } from "../middleware/auth.mjs";

export function createAttendanceRoutes() {
  return {
    matchRoute(method, parts, { store }) {
      const tenantId = parts[2];

      if (method === "POST" && parts.length === 5 && parts[3] === "attendance") {
        const employeeId = parts[4];
        return {
          params: { tenantId, employeeId },
          handler: async ({ request, params, actor }) => {
            const body = await readJson(request);
            const record = {
              id: body.id ?? `attendance_${Date.now()}`,
              tenantId: params.tenantId,
              employeeId: params.employeeId,
              date: body.date,
              checkIn: body.checkIn ?? null,
              checkOut: body.checkOut ?? null,
              status: body.status ?? "present",
              recordedBy: actor.userId,
              createdAt: new Date().toISOString(),
            };
            store.putAttendance(record);
            store.appendAuditLog({ tenantId: params.tenantId, action: "attendance_record", employeeId: params.employeeId, recordId: record.id, actor: actor.userId });
            return jsonResponse(201, record);
          },
        };
      }

      if (method === "GET" && parts.length === 5 && parts[3] === "attendance") {
        return {
          params: { tenantId, employeeId: parts[4] },
          handler: async ({ request, params }) => {
            const url = new URL(request.url);
            const records = store.listAttendanceByEmployee(params.tenantId, params.employeeId);
            return jsonResponse(200, { items: records, employeeId: params.employeeId });
          },
        };
      }

      if (method === "GET" && parts.length === 4 && parts[3] === "attendance") {
        return {
          params: { tenantId },
          handler: async ({ request, params }) => {
            const url = new URL(request.url);
            const employeeId = url.searchParams.get("employeeId");
            if (!employeeId) return jsonResponse(400, { error: "employeeId_query_param_required" });
            const records = store.listAttendanceByEmployee(params.tenantId, employeeId);
            return jsonResponse(200, { items: records, employeeId });
          },
        };
      }

      return null;
    },
  };
}
