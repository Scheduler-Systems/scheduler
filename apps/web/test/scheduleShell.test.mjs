import assert from "node:assert/strict";
import test from "node:test";
import { mockSchedule } from "../app/src/mockSchedule.js";

test("mock schedule exposes manager and worker modes", () => {
  assert.equal(mockSchedule.tenantId, "tenant_security_demo");
  assert.match(mockSchedule.managerMode.label, /review/);
  assert.match(mockSchedule.workerMode.label, /view/);
  assert.equal(mockSchedule.shifts.length, 2);
});
