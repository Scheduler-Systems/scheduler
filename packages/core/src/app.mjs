import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import { createAgentRoutes } from "./routes/agents.mjs";

const require = createRequire(import.meta.url);

const jsonHeaders = {
  "content-type": "application/json; charset=utf-8",
};

export function resolveStore(env = process.env) {
  const storeType = env.SCHEDULER_STORE || "memory";

  if (storeType === "firebase" || storeType === "firestore") {
    try {
      require("firebase-admin");
      const { createFirebaseStore } = require("../src/store/firebase.mjs");
      return createFirebaseStore();
    } catch (error) {
      console.error("Firebase store unavailable:", error.message);
      if (env.NODE_ENV === "production") throw error;
      console.warn("Falling back to memory store");
    }
  }

  return createMemoryStore();
}

export function createSchedulerApi(options = {}) {
  const store = options.store ?? resolveStore();
  const rateLimit = options.rateLimit ?? createMemoryRateLimit(1000);
  const langsmithApiKey = options.langsmithApiKey ?? process.env.LANGSMITH_API_KEY ?? null;
  const dispatchSecret = options.dispatchSecret ?? process.env.SCHEDULER_DISPATCH_SECRET ?? null;

  const agentRoutes = createAgentRoutes({ langsmithApiKey, dispatchSecret });

  return async function handleRequest(request) {
    const url = new URL(request.url);
    const parts = url.pathname.split("/").filter(Boolean);

    // Try agent routes first — they handle /v1/tenants/{tid}/agents/...
    // and may skip standard user auth (dispatch endpoint uses its own secret)
    const agentRoute = parts[0] === "v1" && parts[1] === "tenants" && parts[3] === "agents"
      ? agentRoutes.matchRoute(request.method, parts, { store })
      : null;

    if (agentRoute) {
      if (!agentRoute.skipUserAuth) {
        const auth = authenticate(request, agentRoute.params.tenantId);
        if (!auth.ok) return jsonResponse(auth.status, { error: auth.error });
        if (agentRoute.managerOnly && !hasManagerApprovalBoundary(auth.actor)) {
          return jsonResponse(403, { error: "manager_approval_required" });
        }
        const limited = rateLimit.check(auth.actor.tenantId);
        if (!limited.ok) {
          return jsonResponse(429, { error: "rate_limited", retryAfter: limited.retryAfter });
        }
      }
      try {
        return await agentRoute.handler({ request, params: agentRoute.params, store });
      } catch (error) {
        return jsonResponse(400, { error: "bad_request", message: error.message });
      }
    }

    const route = matchRoute(request.method, url.pathname);

    if (!route) {
      return jsonResponse(404, { error: "not_found" });
    }

    const auth = authenticate(request, route.params.tenantId);
    if (!auth.ok) {
      return jsonResponse(auth.status, { error: auth.error });
    }

    if (route.managerOnly && !hasManagerApprovalBoundary(auth.actor)) {
      return jsonResponse(403, { error: "manager_approval_required" });
    }

    const limited = rateLimit.check(auth.actor.tenantId);
    if (!limited.ok) {
      return jsonResponse(429, {
        error: "rate_limited",
        retryAfter: limited.retryAfter,
      });
    }

    try {
      return await route.handler({
        request,
        params: route.params,
        actor: auth.actor,
        store,
      });
    } catch (error) {
      return jsonResponse(400, {
        error: "bad_request",
        message: error.message,
      });
    }
  };
}

export function createMemoryStore() {
  const schedules = new Map();
  const availability = new Map();
  const drafts = new Map();
  const requests = new Map();
  const imports = new Map();
  const approvals = new Map();
  const employees = new Map();
  const auditLogs = [];

  return {
    listSchedules(tenantId) {
      return [...schedules.values()]
        .filter((s) => s.tenantId === tenantId)
        .sort((a, b) => b.createdAt - a.createdAt);
    },
    putSchedule(schedule) {
      const key = `${schedule.tenantId}:${schedule.id}`;
      const existing = schedules.get(key);
      const merged = {
        ...existing,
        ...schedule,
        updatedAt: new Date().toISOString(),
      };
      if (!merged.createdAt) merged.createdAt = new Date().toISOString();
      schedules.set(key, merged);
      return merged;
    },
    getSchedule(tenantId, scheduleId) {
      return schedules.get(`${tenantId}:${scheduleId}`) ?? null;
    },
    deleteSchedule(tenantId, scheduleId) {
      schedules.delete(`${tenantId}:${scheduleId}`);
    },
    putAvailability(entry) {
      availability.set(`${entry.id}`, entry);
      return entry;
    },
    getAvailability(id) {
      return availability.get(id) ?? null;
    },
    putDraft(draft) {
      drafts.set(draft.id, draft);
      return draft;
    },
    getDraft(id) {
      return drafts.get(id) ?? null;
    },
    deleteDraft(id) {
      drafts.delete(id);
    },
    putRequest(req) {
      requests.set(req.id, req);
      return req;
    },
    getRequest(id) {
      return requests.get(id) ?? null;
    },
    putImport(result) {
      imports.set(result.importId, result);
      return result;
    },
    getImport(importId) {
      return imports.get(importId) ?? null;
    },
    listImports(tenantId, limit = 50) {
      return [...imports.values()]
        .filter((imp) => imp.tenantId === tenantId)
        .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
        .slice(0, Math.min(limit, 100));
    },
    putApproval(approval) {
      approvals.set(approval.id, approval);
      return approval;
    },
    listEmployees(tenantId) {
      return [...employees.values()].filter((e) => e.tenantId === tenantId);
    },
    putEmployee(employee) {
      employees.set(`${employee.tenantId}:${employee.id}`, employee);
      return employee;
    },
    getEmployee(tenantId, employeeId) {
      return employees.get(`${tenantId}:${employeeId}`) ?? null;
    },
    deleteEmployee(tenantId, employeeId) {
      employees.delete(`${tenantId}:${employeeId}`);
    },
    listAgents(tenantId) {
      return [...employees.values()].filter(
        (e) => e.tenantId === tenantId && e.role === "agent"
      );
    },
    appendAuditLog(entry) {
      auditLogs.push({ ...entry, timestamp: new Date().toISOString() });
    },
  };
}

export function createMemoryRateLimit(maxPerMinute = 1000) {
  const buckets = new Map();

  return {
    check(tenantId) {
      const now = Date.now();
      const window = 60_000;
      let bucket = buckets.get(tenantId);

      if (!bucket || now - bucket.startedAt > window) {
        bucket = { startedAt: now, count: 0 };
        buckets.set(tenantId, bucket);
      }

      bucket.count++;

      if (bucket.count > maxPerMinute) {
        return {
          ok: false,
          retryAfter: Math.ceil((bucket.startedAt + window - now) / 1000),
        };
      }

      return { ok: true };
    },
  };
}

function matchRoute(method, pathname) {
  const parts = pathname.split("/").filter(Boolean);

  if (parts[0] !== "v1" || parts[1] !== "tenants" || !parts[2]) {
    return null;
  }

  const tenantId = parts[2];

  // GET /v1/tenants/{tenantId}/schedules
  if (method === "GET" && parts.length === 4 && parts[3] === "schedules") {
    return {
      params: { tenantId },
      handler: async ({ params, store }) =>
        jsonResponse(200, { items: store.listSchedules(params.tenantId) }),
    };
  }

  // POST /v1/tenants/{tenantId}/schedules
  if (method === "POST" && parts.length === 4 && parts[3] === "schedules") {
    return {
      managerOnly: true,
      params: { tenantId },
      handler: async ({ request, params, store, actor }) => {
        const body = await readJson(request);
        if (!body.name || typeof body.name !== "string") {
          return jsonResponse(400, {
            error: "invalid_argument",
            message: "Schedule name is required",
          });
        }

        const id = body.id || `schedule_${Date.now()}`;
        const schedule = {
          id,
          tenantId: params.tenantId,
          name: body.name,
          settings: body.settings || {},
          status: body.status || "draft",
          createdBy: actor.userId,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        };
        return jsonResponse(201, store.putSchedule(schedule));
      },
    };
  }

  // GET /v1/tenants/{tenantId}/schedules/{scheduleId}
  if (method === "GET" && parts.length === 5 && parts[3] === "schedules") {
    return {
      params: { tenantId, scheduleId: parts[4] },
      handler: async ({ params, store }) => {
        const schedule = store.getSchedule(params.tenantId, params.scheduleId);
        return schedule
          ? jsonResponse(200, schedule)
          : jsonResponse(404, { error: "schedule_not_found" });
      },
    };
  }

  // PATCH /v1/tenants/{tenantId}/schedules/{scheduleId}
  if (method === "PATCH" && parts.length === 5 && parts[3] === "schedules") {
    return {
      managerOnly: true,
      params: { tenantId, scheduleId: parts[4] },
      handler: async ({ request, params, store }) => {
        const body = await readJson(request);
        const updates = body.updates;
        if (!updates || typeof updates !== "object") {
          return jsonResponse(400, {
            error: "invalid_argument",
            message: "Updates are required",
          });
        }

        const existing = store.getSchedule(params.tenantId, params.scheduleId);
        if (!existing) {
          return jsonResponse(404, { error: "schedule_not_found" });
        }

        const allowed = {};
        for (const field of ["name", "settings", "status"]) {
          if (updates[field] !== undefined) {
            allowed[field] = updates[field];
          }
        }

        const updated = store.putSchedule({ ...existing, ...allowed });
        return jsonResponse(200, updated);
      },
    };
  }

  // DELETE /v1/tenants/{tenantId}/schedules/{scheduleId}
  if (method === "DELETE" && parts.length === 5 && parts[3] === "schedules") {
    return {
      managerOnly: true,
      params: { tenantId, scheduleId: parts[4] },
      handler: async ({ params, store }) => {
        const existing = store.getSchedule(params.tenantId, params.scheduleId);
        if (!existing) {
          return jsonResponse(404, { error: "schedule_not_found" });
        }
        store.deleteSchedule(params.tenantId, params.scheduleId);
        return jsonResponse(200, { success: true, id: params.scheduleId });
      },
    };
  }

  // POST /v1/tenants/{tenantId}/schedules/{scheduleId}/availability
  if (
    method === "POST" &&
    parts.length === 6 &&
    parts[3] === "schedules" &&
    parts[5] === "availability"
  ) {
    return {
      params: { tenantId, scheduleId: parts[4] },
      handler: async ({ request, params, store, actor }) => {
        const body = await readJson(request);

        const existing = store.getSchedule(params.tenantId, params.scheduleId);
        if (!existing) {
          return jsonResponse(404, { error: "schedule_not_found" });
        }

        const id = body.approvalId || `approval_${Date.now()}`;
        const entry = {
          id,
          tenantId: params.tenantId,
          scheduleId: params.scheduleId,
          userId: actor.userId,
          availability: body.availability || {},
          state: "pending",
          createdAt: new Date().toISOString(),
        };

        store.putAvailability(entry);
        return jsonResponse(202, entry);
      },
    };
  }

  // POST /v1/tenants/{tenantId}/schedules/{scheduleId}/drafts
  if (
    method === "POST" &&
    parts.length === 6 &&
    parts[3] === "schedules" &&
    parts[5] === "drafts"
  ) {
    return {
      managerOnly: true,
      params: { tenantId, scheduleId: parts[4] },
      handler: async ({ request, params, store, actor }) => {
        const body = await readJson(request);

        const existing = store.getSchedule(params.tenantId, params.scheduleId);
        if (!existing) {
          return jsonResponse(404, { error: "schedule_not_found" });
        }

        const draft = {
          id: `draft_${Date.now()}`,
          tenantId: params.tenantId,
          scheduleId: params.scheduleId,
          shifts: body.shifts || [],
          createdBy: actor.userId,
          createdAt: new Date().toISOString(),
        };

        store.putDraft(draft);
        return jsonResponse(201, draft);
      },
    };
  }

  // POST /v1/tenants/{tenantId}/schedules/{scheduleId}/publish
  if (
    method === "POST" &&
    parts.length === 6 &&
    parts[3] === "schedules" &&
    parts[5] === "publish"
  ) {
    return {
      managerOnly: true,
      params: { tenantId, scheduleId: parts[4] },
      handler: async ({ request, params, store, actor }) => {
        const body = await readJson(request);
        const draftId = body.draftId;

        if (!draftId) {
          return jsonResponse(400, {
            error: "invalid_argument",
            message: "Draft ID is required",
          });
        }

        const draft = store.getDraft(draftId);
        if (!draft) {
          return jsonResponse(404, { error: "draft_not_found" });
        }

        if (
          draft.tenantId !== params.tenantId ||
          draft.scheduleId !== params.scheduleId
        ) {
          return jsonResponse(404, { error: "draft_not_found" });
        }

        const schedule = store.getSchedule(params.tenantId, params.scheduleId);
        if (!schedule) {
          return jsonResponse(404, { error: "schedule_not_found" });
        }

        const published = store.putSchedule({
          ...schedule,
          status: "published",
          publishedAt: new Date().toISOString(),
          publishedBy: actor.userId,
        });

        store.deleteDraft(draftId);

        return jsonResponse(200, {
          id: published.id,
          tenantId: published.tenantId,
          scheduleId: published.id,
          draftId,
          publishedAt: published.publishedAt,
        });
      },
    };
  }

  // POST /v1/tenants/{tenantId}/schedules/{scheduleId}/requests
  if (
    method === "POST" &&
    parts.length === 6 &&
    parts[3] === "schedules" &&
    parts[5] === "requests"
  ) {
    return {
      params: { tenantId, scheduleId: parts[4] },
      handler: async ({ request, params, store, actor }) => {
        const body = await readJson(request);

        const existing = store.getSchedule(params.tenantId, params.scheduleId);
        if (!existing) {
          return jsonResponse(404, { error: "schedule_not_found" });
        }

        const id = body.id || `request_${Date.now()}`;
        const entry = {
          id,
          tenantId: params.tenantId,
          scheduleId: params.scheduleId,
          userId: actor.userId,
          type: body.type || "general",
          details: body.details || {},
          state: "pending",
          createdAt: new Date().toISOString(),
        };

        store.putRequest(entry);
        return jsonResponse(202, entry);
      },
    };
  }

  // POST /v1/tenants/{tenantId}/schedgy/approved-constraints:import
  if (
    method === "POST" &&
    parts.length === 5 &&
    parts[3] === "schedgy" &&
    parts[4] === "approved-constraints:import"
  ) {
    return {
      managerOnly: true,
      params: { tenantId },
      handler: async ({ request, params, store, actor }) => {
        const body = await readJson(request);

        if (body.sourceSystem !== "schedgy") {
          return jsonResponse(400, {
            error: "invalid_argument",
            message: "sourceSystem must be schedgy",
          });
        }

        const approvedConstraints = body.approvedConstraints;
        if (
          !Array.isArray(approvedConstraints) ||
          approvedConstraints.length === 0
        ) {
          return jsonResponse(400, {
            error: "invalid_argument",
            message: "approvedConstraints must be a non-empty array",
          });
        }

        const importId = `schedgy_import_${Date.now()}`;
        const approvalId = `approval_${Date.now()}`;

        const importedConstraintIds = [];
        for (const item of approvedConstraints) {
          if (item.constraint && item.constraint.id) {
            importedConstraintIds.push(item.constraint.id);
          }
        }

        const importRecord = {
          importId,
          tenantId: params.tenantId,
          sourceSystem: body.sourceSystem,
          importedConstraintIds,
          totalConstraints: approvedConstraints.length,
          importedCount: importedConstraintIds.length,
          metadata: body.metadata || {},
          createdBy: actor.userId,
          createdAt: Date.now(),
        };

        const approvalRecord = {
          id: approvalId,
          tenantId: params.tenantId,
          importId,
          state: "pending",
          constraintsReviewed: importedConstraintIds.length,
          createdAt: new Date().toISOString(),
        };

        store.putImport(importRecord);
        store.putApproval(approvalRecord);

        return jsonResponse(202, {
          importId,
          tenantId: params.tenantId,
          importedConstraintIds,
          approvalState: {
            id: approvalId,
            tenantId: params.tenantId,
            state: "pending",
          },
        });
      },
    };
  }

  // GET /v1/tenants/{tenantId}/schedgy/imports/{importId}
  if (
    method === "GET" &&
    parts.length === 6 &&
    parts[3] === "schedgy" &&
    parts[4] === "imports"
  ) {
    return {
      params: { tenantId, importId: parts[5] },
      handler: async ({ params, store }) => {
        const imp = store.getImport(params.importId);
        if (!imp) {
          return jsonResponse(404, { error: "import_not_found" });
        }
        if (imp.tenantId !== params.tenantId) {
          return jsonResponse(404, { error: "import_not_found" });
        }
        return jsonResponse(200, imp);
      },
    };
  }

  // GET /v1/tenants/{tenantId}/schedgy/imports
  if (
    method === "GET" &&
    parts.length === 5 &&
    parts[3] === "schedgy" &&
    parts[4] === "imports"
  ) {
    return {
      params: { tenantId },
      handler: async ({ request, params, store }) => {
        const url = new URL(request.url);
        const limit = parseInt(url.searchParams.get("limit") || "50", 10);
        return jsonResponse(200, {
          items: store.listImports(params.tenantId, limit),
        });
      },
    };
  }

  // GET /v1/tenants/{tenantId}/healthz
  if (method === "GET" && parts.length === 4 && parts[3] === "healthz") {
    return {
      params: { tenantId },
      handler: async () =>
        jsonResponse(200, {
          schemaVersion: "scheduler.health.v1",
          service: "Scheduler",
          status: "ok",
          requestId: randomUUID(),
          generatedAt: new Date().toISOString(),
        }),
    };
  }

  // GET /v1/tenants/{tenantId}/readyz
  if (method === "GET" && parts.length === 4 && parts[3] === "readyz") {
    return {
      params: { tenantId },
      handler: async () => {
        const check = {
          id: "store-read",
          name: "Store read",
          status: "ok",
          criticality: "critical",
          checkedAt: new Date().toISOString(),
          latencyMs: 0,
          message: null,
        };
        return jsonResponse(200, {
          schemaVersion: "scheduler.readiness.v1",
          service: "Scheduler",
          status: "ok",
          ready: true,
          requestId: randomUUID(),
          generatedAt: new Date().toISOString(),
          checks: [check],
        });
      },
    };
  }

  // GET /v1/tenants/{tenantId}/status
  if (method === "GET" && parts.length === 4 && parts[3] === "status") {
    return {
      params: { tenantId },
      handler: async () =>
        jsonResponse(200, {
          schemaVersion: "scheduler.status.v1",
          service: "Scheduler",
          status: "ok",
          requestId: randomUUID(),
          generatedAt: new Date().toISOString(),
          dependencies: [
            {
              id: "firestore",
              name: "Firestore",
              type: "firebase",
              criticality: "critical",
              customerImpact:
                "Schedules, employees, priorities, chat, and profile reads or writes may fail.",
            },
          ],
          checks: [],
        }),
    };
  }

  // PUT /v1/tenants/{tenantId}/schedules/{scheduleId}
  if (method === "PUT" && parts.length === 5 && parts[3] === "schedules") {
    return {
      managerOnly: true,
      params: { tenantId, scheduleId: parts[4] },
      handler: async ({ request, params, store }) => {
        const body = await readJson(request);
        const existing = store.getSchedule(params.tenantId, params.scheduleId);
        if (!existing) {
          return jsonResponse(404, { error: "schedule_not_found" });
        }

        const updated = store.putSchedule({
          ...existing,
          name: body.name !== undefined ? body.name : existing.name,
          settings:
            body.settings !== undefined ? body.settings : existing.settings,
          status: body.status !== undefined ? body.status : existing.status,
        });
        return jsonResponse(200, updated);
      },
    };
  }

  return null;
}

function authenticate(request, tenantId) {
  const authorization = request.headers.get("authorization");
  const actorTenantId = request.headers.get("x-tenant-id");
  const actorUserId = request.headers.get("x-user-id");
  const actorRole = request.headers.get("x-user-role") ?? "employee";
  const correlationId = request.headers.get("x-correlation-id");

  if (!authorization?.startsWith("Bearer ")) {
    return { ok: false, status: 401, error: "missing_bearer_token" };
  }

  if (!actorTenantId || actorTenantId !== tenantId) {
    return { ok: false, status: 403, error: "tenant_mismatch" };
  }

  if (!actorUserId || !correlationId) {
    return { ok: false, status: 400, error: "missing_actor_context" };
  }

  return {
    ok: true,
    actor: {
      tenantId: actorTenantId,
      userId: actorUserId,
      role: actorRole,
      correlationId,
    },
  };
}

function hasManagerApprovalBoundary(actor) {
  return actor.role === "manager" || actor.role === "owner";
}

async function readJson(request) {
  if (request.method === "GET") {
    return {};
  }
  const text = await request.text();
  return text ? JSON.parse(text) : {};
}

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: jsonHeaders,
  });
}
