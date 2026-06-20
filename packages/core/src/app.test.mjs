// Engine tests for packages/core. Run with: node --test
import { test } from "node:test";
import assert from "node:assert/strict";
import { createSchedulerApi, createMemoryStore } from "./index.mjs";

// Build a fetch-style Request the handler understands.
function req(method, path, { headers = {}, body } = {}) {
  return new Request(`http://localhost${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

// Valid actor context (the handler requires bearer + tenant + user + correlation).
const managerHeaders = (tid) => ({
  authorization: "Bearer test-token",
  "x-tenant-id": tid,
  "x-user-id": "user-1",
  "x-user-role": "manager",
  "x-correlation-id": "corr-1",
});

test("memory store round-trips a schedule", () => {
  const store = createMemoryStore();
  const saved = store.putSchedule({ id: "s1", tenantId: "t1", name: "Test" });
  assert.equal(saved.id, "s1");
  assert.equal(store.getSchedule("t1", "s1").name, "Test");
  assert.equal(store.listSchedules("t1").length, 1);
  store.deleteSchedule("t1", "s1");
  assert.equal(store.getSchedule("t1", "s1"), null);
});

test("healthz returns ok", async () => {
  const api = createSchedulerApi({ store: createMemoryStore() });
  const res = await api(req("GET", "/v1/tenants/t1/healthz", { headers: managerHeaders("t1") }));
  assert.equal(res.status, 200);
  assert.equal((await res.json()).status, "ok");
});

test("missing bearer token is rejected (401)", async () => {
  const api = createSchedulerApi({ store: createMemoryStore() });
  const res = await api(req("GET", "/v1/tenants/t1/schedules"));
  assert.equal(res.status, 401);
});

test("tenant mismatch is rejected (403)", async () => {
  const api = createSchedulerApi({ store: createMemoryStore() });
  const res = await api(
    req("GET", "/v1/tenants/t1/schedules", {
      headers: { ...managerHeaders("t1"), "x-tenant-id": "other-tenant" },
    }),
  );
  assert.equal(res.status, 403);
});

test("create then list a schedule", async () => {
  const api = createSchedulerApi({ store: createMemoryStore() });
  const created = await api(
    req("POST", "/v1/tenants/t1/schedules", { headers: managerHeaders("t1"), body: { name: "Q3" } }),
  );
  assert.equal(created.status, 201);

  const list = await api(req("GET", "/v1/tenants/t1/schedules", { headers: managerHeaders("t1") }));
  assert.equal(list.status, 200);
  const body = await list.json();
  assert.equal(body.items.length, 1);
  assert.equal(body.items[0].name, "Q3");
});

test("unknown route returns 404", async () => {
  const api = createSchedulerApi({ store: createMemoryStore() });
  const res = await api(req("GET", "/v1/tenants/t1/nope", { headers: managerHeaders("t1") }));
  assert.equal(res.status, 404);
});
