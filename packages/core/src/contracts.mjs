import crypto from "node:crypto";

export const STATUS_PAGE_URL = "https://status.scheduler-systems.com";
export const STATUS_COMPONENT_ID = "scheduler-api";
export const SERVICE_NAME = "Scheduler";
export const SERVICE_REPO = "Scheduler-Systems/Scheduler";

export const DEPENDENCIES = {
  firestore: {
    id: "firestore",
    name: "Firestore",
    type: "firebase",
    criticality: "critical",
    customerImpact: "Schedules, employees, priorities, chat, and profile reads or writes may fail.",
  },
  firebase_auth: {
    id: "firebase_auth",
    name: "Firebase Auth",
    type: "firebase",
    criticality: "critical",
    customerImpact: "Sign-in, sign-up, and account verification may fail.",
  },
  revenuecat: {
    id: "revenuecat",
    name: "RevenueCat",
    type: "external",
    criticality: "critical",
    customerImpact: "Billing, subscription status, and paywall management may be stale.",
  },
  brevo: {
    id: "brevo",
    name: "Brevo",
    type: "external",
    criticality: "standard",
    customerImpact: "Lifecycle and subscription emails may be delayed.",
  },
  gemini: {
    id: "gemini",
    name: "Gemini",
    type: "external",
    criticality: "standard",
    customerImpact: "AI-assisted scheduling features may be unavailable.",
  },
  intercom: {
    id: "intercom",
    name: "Intercom",
    type: "external",
    criticality: "standard",
    customerImpact: "In-app support chat authentication may fail.",
  },
  fcm: {
    id: "fcm",
    name: "Firebase Cloud Messaging",
    type: "firebase",
    criticality: "standard",
    customerImpact: "Push notifications may be delayed or dropped.",
  },
};

export function makeRequestId(headers = {}) {
  function normalizeHeaderValue(value) {
    if (Array.isArray(value)) return value[0];
    return typeof value === "string" ? value : "";
  }
  function sanitizeRequestId(value) {
    const trimmed = String(value || "").trim();
    if (!trimmed) return "";
    const traceId = trimmed.split(";")[0].split("/")[0];
    const sanitized = traceId.replace(/[^a-zA-Z0-9_.:/-]/g, "");
    if (sanitized.length < 6) return "";
    return sanitized.slice(0, 128);
  }

  const candidates = [
    normalizeHeaderValue(headers["x-request-id"]),
    normalizeHeaderValue(headers["x-correlation-id"]),
    normalizeHeaderValue(headers["x-cloud-trace-context"]),
  ];
  for (const candidate of candidates) {
    const requestId = sanitizeRequestId(candidate);
    if (requestId) return requestId;
  }
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return crypto.randomBytes(16).toString("hex");
}

export function nowIso(now = new Date()) {
  return now.toISOString();
}

export function publicDependencies() {
  return Object.values(DEPENDENCIES).map((dep) => ({
    id: dep.id,
    name: dep.name,
    type: dep.type,
    criticality: dep.criticality,
    customerImpact: dep.customerImpact,
  }));
}

export function normalizeCheck(check) {
  return {
    id: check.id,
    name: check.name || check.id,
    status: check.status || "unknown",
    criticality: check.criticality || "standard",
    checkedAt: check.checkedAt || nowIso(),
    latencyMs: typeof check.latencyMs === "number" ? Math.round(check.latencyMs) : null,
    message: check.message || null,
  };
}

export function overallStatus(checks) {
  const normalized = checks.map(normalizeCheck);
  if (normalized.some((c) => c.criticality === "critical" && c.status !== "ok")) {
    return "unavailable";
  }
  if (normalized.some((c) => c.status !== "ok")) return "degraded";
  return "ok";
}

export function syntheticProbes(baseUrl) {
  return [
    {
      id: "scheduler-functions-healthz",
      componentId: STATUS_COMPONENT_ID,
      name: "Scheduler Functions liveness",
      method: "GET",
      url: `${baseUrl}/healthz`,
      expectedStatuses: [200],
      timeoutMs: 3000,
      mutatesData: false,
    },
    {
      id: "scheduler-functions-readyz",
      componentId: STATUS_COMPONENT_ID,
      name: "Scheduler Functions Firestore readiness",
      method: "GET",
      url: `${baseUrl}/readyz`,
      expectedStatuses: [200, 503],
      timeoutMs: 5000,
      mutatesData: false,
    },
    {
      id: "scheduler-functions-status",
      componentId: STATUS_COMPONENT_ID,
      name: "Scheduler dependency status contract",
      method: "GET",
      url: `${baseUrl}/status`,
      expectedStatuses: [200, 503],
      timeoutMs: 5000,
      mutatesData: false,
    },
  ];
}

export function buildHealthResponse({ requestId, now = new Date() }) {
  return {
    schemaVersion: "scheduler.health.v1",
    service: SERVICE_NAME,
    componentId: STATUS_COMPONENT_ID,
    repo: SERVICE_REPO,
    status: "ok",
    requestId,
    generatedAt: nowIso(now),
    statusPageUrl: STATUS_PAGE_URL,
  };
}

export function buildReadinessResponse({ requestId, checks, now = new Date(), baseUrl }) {
  const normalized = checks.map(normalizeCheck);
  const status = overallStatus(normalized);
  return {
    schemaVersion: "scheduler.readiness.v1",
    service: SERVICE_NAME,
    componentId: STATUS_COMPONENT_ID,
    repo: SERVICE_REPO,
    status,
    ready: status !== "unavailable",
    requestId,
    generatedAt: nowIso(now),
    statusPageUrl: STATUS_PAGE_URL,
    checks: normalized,
    syntheticProbes: syntheticProbes(baseUrl),
  };
}

export function buildStatusResponse({ requestId, checks = [], now = new Date(), baseUrl }) {
  const normalized = checks.map(normalizeCheck);
  const status = normalized.length > 0 ? overallStatus(normalized) : "ok";
  return {
    schemaVersion: "scheduler.status.v1",
    service: SERVICE_NAME,
    componentId: STATUS_COMPONENT_ID,
    repo: SERVICE_REPO,
    status,
    requestId,
    generatedAt: nowIso(now),
    statusPageUrl: STATUS_PAGE_URL,
    canonicalStatusComponentUrl: `${STATUS_PAGE_URL}/status.json#${STATUS_COMPONENT_ID}`,
    dependencies: publicDependencies(),
    checks: normalized,
    syntheticProbes: syntheticProbes(baseUrl),
    semantics: {
      healthz: "Process liveness only. Does not call external providers or mutate data.",
      readyz: "Readiness for the Firebase Functions backend. Performs a safe Firestore read only.",
      status: "Machine-readable Scheduler status contract for Stratus probes and incident correlation.",
    },
  };
}

export function dependencyFailureMetadata({ dependency, operation, error, requestId, upstreamStatus }) {
  const dep = DEPENDENCIES[dependency] || {
    id: dependency || "unknown",
    name: dependency || "Unknown dependency",
    criticality: "standard",
  };
  const status =
    typeof upstreamStatus === "number"
      ? upstreamStatus
      : typeof error?.statusCode === "number"
        ? error.statusCode
        : typeof error?.status === "number"
          ? error.status
          : null;
  const message =
    typeof error?.message === "string" && error.message.length > 0
      ? error.message
      : "Dependency request failed";
  return {
    requestId,
    dependency: dep.id,
    dependencyName: dep.name,
    operation,
    statusPageUrl: STATUS_PAGE_URL,
    componentId: STATUS_COMPONENT_ID,
    upstreamStatus: status,
    retryable: status === null || status === 408 || status === 409 || status === 423 || status === 429 || status >= 500,
    message: message.slice(0, 240),
  };
}

export function logDependencyFailure(logger, metadata) {
  const log = logger && typeof logger.error === "function" ? logger.error.bind(logger) : console.error;
  log("[scheduler-status] dependency failure", metadata);
}
