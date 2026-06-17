"use client";

import { getFirebaseAuth } from "@/lib/firebase";

const BASE_URL = process.env.NEXT_PUBLIC_SCHEDULER_API_URL ?? "";

function tenantId(): string {
  // SCRUBBED: set NEXT_PUBLIC_FIREBASE_PROJECT_ID to your own project id.
  return process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "your-firebase-project-id";
}

async function headers(): Promise<Record<string, string>> {
  const auth = getFirebaseAuth();
  const user = auth.currentUser;
  const token = user ? await user.getIdToken() : "";
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
    "x-tenant-id": tenantId(),
    "x-user-id": user?.uid ?? "",
    "x-user-role": "manager",
    "x-correlation-id": crypto.randomUUID(),
  };
}

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const hdrs = { ...(await headers()), ...opts.headers };
  const res = await fetch(`${BASE_URL}${path}`, { ...opts, headers: hdrs });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(
      (body as { message?: string }).message ??
        `API ${res.status}: ${res.statusText}`,
    );
  }
  return body as T;
}

// ---- Types ----

export interface ApiSchedule {
  id: string;
  tenantId: string;
  name: string;
  settings: Record<string, unknown>;
  status: string;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
}

export interface ApiDraft {
  id: string;
  tenantId: string;
  scheduleId: string;
  shifts: unknown[];
  createdBy: string;
  createdAt: string;
}

export interface ApiRequest {
  id: string;
  tenantId: string;
  scheduleId: string;
  userId: string;
  type: string;
  details: Record<string, unknown>;
  state: string;
  createdAt: string;
}

// ---- Schedule CRUD ----

export function listSchedules(): Promise<{ items: ApiSchedule[] }> {
  return request(`/v1/tenants/${tenantId()}/schedules`);
}

export function getSchedule(scheduleId: string): Promise<ApiSchedule> {
  return request(`/v1/tenants/${tenantId()}/schedules/${scheduleId}`);
}

export function createSchedule(input: {
  name: string;
  id?: string;
  settings?: Record<string, unknown>;
}): Promise<ApiSchedule> {
  return request(`/v1/tenants/${tenantId()}/schedules`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateSchedule(
  scheduleId: string,
  updates: Record<string, unknown>,
): Promise<ApiSchedule> {
  return request(`/v1/tenants/${tenantId()}/schedules/${scheduleId}`, {
    method: "PATCH",
    body: JSON.stringify({ updates }),
  });
}

export function deleteSchedule(
  scheduleId: string,
): Promise<{ success: boolean; id: string }> {
  return request(`/v1/tenants/${tenantId()}/schedules/${scheduleId}`, {
    method: "DELETE",
  });
}

// ---- Drafts ----

export function createDraft(
  scheduleId: string,
  shifts: unknown[],
): Promise<ApiDraft> {
  return request(`/v1/tenants/${tenantId()}/schedules/${scheduleId}/drafts`, {
    method: "POST",
    body: JSON.stringify({ shifts }),
  });
}

export function publishDraft(
  scheduleId: string,
  draftId: string,
): Promise<{ id: string; publishedAt: string }> {
  return request(`/v1/tenants/${tenantId()}/schedules/${scheduleId}/publish`, {
    method: "POST",
    body: JSON.stringify({ draftId }),
  });
}

// ---- Availability ----

export function submitAvailability(
  scheduleId: string,
  availability: Record<string, unknown>,
): Promise<{ id: string; state: string }> {
  return request(
    `/v1/tenants/${tenantId()}/schedules/${scheduleId}/availability`,
    {
      method: "POST",
      body: JSON.stringify({ availability }),
    },
  );
}

// ---- Requests ----

export function createRequest(
  scheduleId: string,
  type: string,
  details: Record<string, unknown>,
): Promise<ApiRequest> {
  return request(`/v1/tenants/${tenantId()}/schedules/${scheduleId}/requests`, {
    method: "POST",
    body: JSON.stringify({ type, details }),
  });
}
