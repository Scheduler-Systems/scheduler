import { jsonResponse, readJson } from "../middleware/auth.mjs";

export function createStationRoutes() {
  return {
    matchRoute(method, parts, { store }) {
      const tenantId = parts[2];

      // GET /v1/tenants/{tenantId}/stations/{stationId}/entitlements
      if (method === "GET" && parts.length === 6 && parts[3] === "stations" && parts[5] === "entitlements") {
        return {
          params: { tenantId, stationId: parts[4] },
          handler: async ({ params }) => {
            const entitlement = store.getStationEntitlement(params.tenantId, params.stationId);
            if (!entitlement) {
              return jsonResponse(200, { stationId: params.stationId, entitlements: [], active: false });
            }
            return jsonResponse(200, entitlement);
          },
        };
      }

      // POST /v1/tenants/{tenantId}/stations/{stationId}/entitlements
      if (method === "POST" && parts.length === 6 && parts[3] === "stations" && parts[5] === "entitlements") {
        return {
          managerOnly: true,
          params: { tenantId, stationId: parts[4] },
          handler: async ({ request, params, actor }) => {
            const body = await readJson(request);
            const entitlement = {
              stationId: params.stationId,
              tenantId: params.tenantId,
              entitlements: body.entitlements ?? [],
              active: body.active ?? true,
              updatedBy: actor.userId,
              updatedAt: new Date().toISOString(),
            };
            store.putStationEntitlement(entitlement);
            store.appendAuditLog({ tenantId: params.tenantId, action: "station_entitlement_update", stationId: params.stationId, actor: actor.userId });
            return jsonResponse(200, entitlement);
          },
        };
      }

      // POST /v1/tenants/{tenantId}/stations/{stationId}/check-entitlement
      if (method === "POST" && parts.length === 6 && parts[3] === "stations" && parts[5] === "check-entitlement") {
        return {
          params: { tenantId, stationId: parts[4] },
          handler: async ({ request, params }) => {
            const body = await readJson(request);
            const entitlement = store.getStationEntitlement(params.tenantId, params.stationId);
            const hasAccess = entitlement?.active && entitlement?.entitlements?.includes(body.entitlementKey);
            return jsonResponse(200, {
              stationId: params.stationId,
              entitlementKey: body.entitlementKey,
              hasAccess: !!hasAccess,
            });
          },
        };
      }

      return null;
    },
  };
}
