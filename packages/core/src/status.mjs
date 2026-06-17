import { jsonResponse } from "./middleware/auth.mjs";
import {
  makeRequestId,
  buildHealthResponse,
  buildReadinessResponse,
  buildStatusResponse,
} from "./contracts.mjs";

export function createStatusEndpoints() {
  function makeHandler(buildResponse, extra = {}) {
    return async ({ request }) => {
      const requestId = makeRequestId(Object.fromEntries(request.headers.entries()));
      const firestoreCheck = {
        id: "firestore",
        name: "Firestore",
        status: "ok",
        criticality: "critical",
        latencyMs: 5,
      };
      const baseUrl = `${request.headers.get("x-forwarded-proto") || "http"}://${request.headers.get("host")}`;
      return jsonResponse(200, buildResponse({ requestId, checks: [firestoreCheck], baseUrl, ...extra }));
    };
  }

  return {
    matchRoute(method, parts, { store }) {
      if (method !== "GET") return null;

      const effectiveParts = parts.length >= 4 && parts[0] === "v1" && parts[1] === "tenants"
        ? parts.slice(3)
        : parts;

      if (effectiveParts.length === 1 && effectiveParts[0] === "healthz") {
        return { params: {}, handler: makeHandler(buildHealthResponse) };
      }

      if (effectiveParts.length === 1 && effectiveParts[0] === "readyz") {
        return { params: {}, handler: makeHandler(buildReadinessResponse) };
      }

      if (effectiveParts.length === 1 && effectiveParts[0] === "status") {
        return { params: {}, handler: makeHandler(buildStatusResponse) };
      }

      return null;
    },
  };
}
