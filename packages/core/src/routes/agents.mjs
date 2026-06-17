import { jsonResponse, readJson } from "../middleware/auth.mjs";

const DISPATCH_SECRET_HEADER = "x-dispatch-secret";

// Evaluates whether a 5-field cron expression was due within the last
// windowMinutes minutes relative to `now`. Patterns supported:
//   "0 H * * *"     daily at hour H (UTC)
//   "0 H * * D"     weekly on weekday D at hour H (UTC)
//   "star/M * * * *"  every M minutes (star = asterisk)
export function isCronDue(cronExpression, now = new Date(), windowMinutes = 3) {
  if (!cronExpression) return false;
  const parts = cronExpression.trim().split(/\s+/);
  if (parts.length !== 5) return false;
  const [minute, hour, , , weekday] = parts;

  const checkMinute = (val, field) => {
    if (field === "*") return true;
    const everyMatch = field.match(/^\*\/(\d+)$/);
    if (everyMatch) return val % parseInt(everyMatch[1], 10) === 0;
    return parseInt(field, 10) === val;
  };

  for (let offset = 0; offset < windowMinutes; offset++) {
    const t = new Date(now.getTime() - offset * 60_000);
    const m = t.getUTCMinutes();
    const h = t.getUTCHours();
    const d = t.getUTCDay();

    if (!checkMinute(m, minute)) continue;
    if (!checkMinute(h, hour)) continue;
    if (weekday !== "*" && !checkMinute(d, weekday)) continue;
    return true;
  }
  return false;
}

export async function fireLangSmith(agentConfig, langsmithApiKey, meta) {
  const { assistantId, deploymentUrl, graph } = agentConfig;
  const url = `${deploymentUrl}/runs`;
  const headers = {
    "x-api-key": langsmithApiKey,
    "Content-Type": "application/json",
  };
  // Multi-tenant LangGraph deployments REQUIRE the tenant header to route/authorize a run —
  // without it the deployment returns 403 Forbidden regardless of the API key (this was the
  // long-standing "blocked on a key" wall: it was a missing header, not a permission). The
  // LangSmith tenant is the deployment's workspace tenant — distinct from the Scheduler
  // customer tenant in `meta.tenantId`.
  const langsmithTenantId = agentConfig.langsmithTenantId ?? process.env.LANGSMITH_TENANT_ID;
  if (langsmithTenantId) headers["X-Tenant-Id"] = langsmithTenantId;
  const resp = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify({
      assistant_id: assistantId,
      input: { event: "shift_start", ...meta },
      metadata: { source: "scheduler-platform", ...meta },
    }),
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`LangSmith error ${resp.status}: ${text}`);
  }
  return resp.json();
}

export function createAgentRoutes({ langsmithApiKey, dispatchSecret }) {
  return {
    matchRoute(method, parts, { store }) {
      const tenantId = parts[2];

      // GET /v1/tenants/{tenantId}/agents
      if (method === "GET" && parts.length === 4 && parts[3] === "agents") {
        return {
          params: { tenantId },
          handler: async ({ params }) =>
            jsonResponse(200, { items: store.listAgents(params.tenantId) }),
        };
      }

      // POST /v1/tenants/{tenantId}/agents
      if (method === "POST" && parts.length === 4 && parts[3] === "agents") {
        return {
          managerOnly: true,
          params: { tenantId },
          handler: async ({ request, params, actor }) => {
            const body = await readJson(request);
            if (!body.name) {
              return jsonResponse(400, { error: "invalid_argument", message: "name is required" });
            }
            const agent = {
              id: body.id ?? `agent_${Date.now()}`,
              tenantId: params.tenantId,
              name: body.name,
              email: body.email ?? null,
              role: "agent",
              agentConfig: body.agentConfig ?? {},
              createdAt: new Date().toISOString(),
              createdBy: actor.userId,
            };
            store.putEmployee(agent);
            store.appendAuditLog({ tenantId: params.tenantId, action: "agent_create", agentId: agent.id, actor: actor.userId });
            return jsonResponse(201, agent);
          },
        };
      }

      // GET /v1/tenants/{tenantId}/agents/{agentId}
      if (method === "GET" && parts.length === 5 && parts[3] === "agents") {
        return {
          params: { tenantId, agentId: parts[4] },
          handler: async ({ params }) => {
            const agent = store.getEmployee(params.tenantId, params.agentId);
            if (!agent || agent.role !== "agent") {
              return jsonResponse(404, { error: "agent_not_found" });
            }
            return jsonResponse(200, agent);
          },
        };
      }

      // PATCH /v1/tenants/{tenantId}/agents/{agentId}
      if (method === "PATCH" && parts.length === 5 && parts[3] === "agents") {
        return {
          managerOnly: true,
          params: { tenantId, agentId: parts[4] },
          handler: async ({ request, params, actor }) => {
            const agent = store.getEmployee(params.tenantId, params.agentId);
            if (!agent || agent.role !== "agent") {
              return jsonResponse(404, { error: "agent_not_found" });
            }
            const body = await readJson(request);
            const updated = { ...agent, ...body, role: "agent", updatedAt: new Date().toISOString() };
            store.putEmployee(updated);
            store.appendAuditLog({ tenantId: params.tenantId, action: "agent_update", agentId: params.agentId, actor: actor.userId });
            return jsonResponse(200, updated);
          },
        };
      }

      // POST /v1/tenants/{tenantId}/agents/{agentId}/fire
      // Manual trigger — called by manager or for testing
      if (method === "POST" && parts.length === 6 && parts[3] === "agents" && parts[5] === "fire") {
        return {
          managerOnly: true,
          params: { tenantId, agentId: parts[4] },
          handler: async ({ params }) => {
            if (!langsmithApiKey) {
              return jsonResponse(503, { error: "agent_dispatch_unavailable", message: "LANGSMITH_API_KEY not configured" });
            }
            const agent = store.getEmployee(params.tenantId, params.agentId);
            if (!agent || agent.role !== "agent") {
              return jsonResponse(404, { error: "agent_not_found" });
            }
            if (!agent.agentConfig?.assistantId || !agent.agentConfig?.deploymentUrl) {
              return jsonResponse(400, { error: "agent_not_configured", message: "agentConfig.assistantId and deploymentUrl required" });
            }
            const result = await fireLangSmith(agent.agentConfig, langsmithApiKey, {
              tenantId: params.tenantId,
              agentId: params.agentId,
              agentName: agent.name,
              trigger: "manual",
            });
            store.appendAuditLog({ tenantId: params.tenantId, action: "agent_fired", agentId: params.agentId, runId: result.run_id });
            return jsonResponse(200, { fired: true, runId: result.run_id, agentId: params.agentId });
          },
        };
      }

      // POST /v1/tenants/{tenantId}/agents/dispatch
      // Called by the Cloudflare Worker cron every minute.
      // Auth: x-dispatch-secret header (not user Bearer token).
      if (method === "POST" && parts.length === 5 && parts[3] === "agents" && parts[4] === "dispatch") {
        return {
          skipUserAuth: true,
          params: { tenantId },
          handler: async ({ request, params }) => {
            if (!dispatchSecret) {
              return jsonResponse(503, { error: "dispatch_unavailable", message: "SCHEDULER_DISPATCH_SECRET not configured" });
            }
            const secret = request.headers.get(DISPATCH_SECRET_HEADER) ?? "";
            if (secret !== dispatchSecret) {
              return jsonResponse(401, { error: "unauthorized" });
            }
            if (!langsmithApiKey) {
              return jsonResponse(503, { error: "dispatch_unavailable", message: "LANGSMITH_API_KEY not configured" });
            }

            const agents = store.listAgents(params.tenantId);
            const now = new Date();
            const dispatched = [];
            const errors = [];

            for (const agent of agents) {
              const { agentConfig } = agent;
              if (!agentConfig?.assistantId || !agentConfig?.deploymentUrl) continue;
              if (!isCronDue(agentConfig.cronExpression, now)) continue;

              try {
                const result = await fireLangSmith(agentConfig, langsmithApiKey, {
                  tenantId: params.tenantId,
                  agentId: agent.id,
                  agentName: agent.name,
                  trigger: "shift_start",
                });
                dispatched.push({ agentId: agent.id, name: agent.name, runId: result.run_id });
                store.appendAuditLog({ tenantId: params.tenantId, action: "agent_fired", agentId: agent.id, runId: result.run_id, trigger: "shift_start" });
              } catch (err) {
                errors.push({ agentId: agent.id, name: agent.name, error: err.message });
              }
            }

            return jsonResponse(200, {
              checkedAt: now.toISOString(),
              agentsChecked: agents.length,
              dispatched,
              errors,
            });
          },
        };
      }

      return null;
    },
  };
}
