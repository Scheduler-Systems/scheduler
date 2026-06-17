import { authenticate, hasManagerApprovalBoundary, jsonResponse, readJson } from "../middleware/auth.mjs";

export function createEmployeeRoutes() {
  return {
    matchRoute(method, parts, { store }) {
      const tenantId = parts[2];

      if (method === "GET" && parts.length === 4 && parts[3] === "employees") {
        return {
          params: { tenantId },
          handler: async ({ params }) =>
            jsonResponse(200, { items: store.listEmployees(params.tenantId) }),
        };
      }

      if (method === "POST" && parts.length === 4 && parts[3] === "employees") {
        return {
          managerOnly: true,
          params: { tenantId },
          handler: async ({ request, params, actor }) => {
            const body = await readJson(request);
            const employee = {
              id: body.id ?? `employee_${Date.now()}`,
              tenantId: params.tenantId,
              name: body.name,
              email: body.email,
              role: body.role ?? "employee",
              stationIds: body.stationIds ?? [],
              maxWeeklyHours: body.maxWeeklyHours ?? null,
              createdAt: new Date().toISOString(),
              createdBy: actor.userId,
            };
            store.appendAuditLog({ tenantId: params.tenantId, action: "employee_create", employeeId: employee.id, actor: actor.userId });
            return jsonResponse(201, store.putEmployee(employee));
          },
        };
      }

      if (method === "GET" && parts.length === 5 && parts[3] === "employees") {
        return {
          params: { tenantId, employeeId: parts[4] },
          handler: async ({ params }) => {
            const employee = store.getEmployee(params.tenantId, params.employeeId);
            return employee
              ? jsonResponse(200, employee)
              : jsonResponse(404, { error: "employee_not_found" });
          },
        };
      }

      if (method === "PATCH" && parts.length === 5 && parts[3] === "employees") {
        return {
          managerOnly: true,
          params: { tenantId, employeeId: parts[4] },
          handler: async ({ request, params, actor }) => {
            const employee = store.getEmployee(params.tenantId, params.employeeId);
            if (!employee) return jsonResponse(404, { error: "employee_not_found" });
            const body = await readJson(request);
            const updated = { ...employee, ...body, updatedAt: new Date().toISOString() };
            store.appendAuditLog({ tenantId: params.tenantId, action: "employee_update", employeeId: params.employeeId, actor: actor.userId });
            return jsonResponse(200, store.putEmployee(updated));
          },
        };
      }

      if (method === "DELETE" && parts.length === 5 && parts[3] === "employees") {
        return {
          managerOnly: true,
          params: { tenantId, employeeId: parts[4] },
          handler: async ({ params, actor }) => {
            const employee = store.getEmployee(params.tenantId, params.employeeId);
            if (!employee) return jsonResponse(404, { error: "employee_not_found" });
            store.deleteEmployee(params.tenantId, params.employeeId);
            store.appendAuditLog({ tenantId: params.tenantId, action: "employee_delete", employeeId: params.employeeId, actor: actor.userId });
            return jsonResponse(200, { deleted: params.employeeId });
          },
        };
      }

      return null;
    },
  };
}
