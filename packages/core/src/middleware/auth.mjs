export function authenticate(request, tenantId) {
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

export function hasManagerApprovalBoundary(actor) {
  return actor.role === "manager" || actor.role === "owner";
}

export const jsonHeaders = {
  "content-type": "application/json; charset=utf-8",
};

export function jsonResponse(status, body, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...jsonHeaders, ...extraHeaders },
  });
}

export async function readJson(request) {
  if (request.method === "GET") return {};
  const text = await request.text();
  return text ? JSON.parse(text) : {};
}
