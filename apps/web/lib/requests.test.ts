import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock firebase/firestore the same way firestore-write.test.ts does —
// each SDK call records its args so we can assert on the exact payload
// written. Reads are backed by small fixture maps.

const calls = {
  addDoc: vi.fn(),
  setDoc: vi.fn(),
  updateDoc: vi.fn(),
  deleteDoc: vi.fn(),
  getDoc: vi.fn(),
  getDocs: vi.fn(),
  batchCommit: vi.fn(),
};

const docFixtures = new Map<string, { exists: boolean; data: unknown }>();
const collectionFixtures = new Map<
  string,
  { id: string; path: string; data: unknown }[]
>();

function setDocFixture(path: string, data: unknown) {
  docFixtures.set(path, { exists: true, data });
}
function missingDocFixture(path: string) {
  docFixtures.set(path, { exists: false, data: null });
}
function setCollectionFixture(
  path: string,
  docs: { id: string; path?: string; data: unknown }[]
) {
  collectionFixtures.set(
    path,
    docs.map((d) => ({ id: d.id, path: d.path ?? `${path}/${d.id}`, data: d.data }))
  );
}

vi.mock("firebase/firestore", () => ({
  collection: (parent: unknown, ...segments: string[]) => {
    // When the first arg is itself a doc ref, treat its path as the prefix
    // (matches Firestore's subcollection-on-doc overload).
    if (parent && typeof parent === "object" && "path" in (parent as Record<string, unknown>)) {
      const parentPath = (parent as { path: string }).path;
      return {
        type: "collection",
        path: [parentPath, ...segments].join("/"),
      };
    }
    return { type: "collection", path: segments.join("/") };
  },
  collectionGroup: (_db: unknown, id: string) => ({
    type: "collectionGroup",
    id,
    path: `__group__/${id}`,
  }),
  doc: (parent: unknown, ...segments: string[]) => {
    // Support `doc(collectionRef)` (auto-id) and `doc(db, ...segments)`.
    if (segments.length === 0 && parent && typeof parent === "object") {
      const cPath = (parent as { path: string }).path;
      return { type: "doc", path: `${cPath}/auto-id`, id: "auto-id" };
    }
    // Support `doc(parentDocRef, 'subcoll', 'id')` as well.
    if (
      parent &&
      typeof parent === "object" &&
      "path" in (parent as Record<string, unknown>) &&
      (parent as { type?: string }).type === "doc"
    ) {
      const parentPath = (parent as { path: string }).path;
      const full = [parentPath, ...segments].join("/");
      return {
        type: "doc",
        path: full,
        id: segments[segments.length - 1],
      };
    }
    return {
      type: "doc",
      path: segments.join("/"),
      id: segments[segments.length - 1],
    };
  },
  DocumentReference: class {},
  addDoc: (ref: { path: string }, data: Record<string, unknown>) => {
    calls.addDoc(ref, data);
    return Promise.resolve({
      id: "new-doc-id",
      path: `${ref.path}/new-doc-id`,
    });
  },
  setDoc: (
    ref: { path: string },
    data: Record<string, unknown>,
    opts?: unknown
  ) => {
    calls.setDoc(ref, data, opts);
    return Promise.resolve();
  },
  updateDoc: (ref: { path: string }, data: Record<string, unknown>) => {
    calls.updateDoc(ref, data);
    return Promise.resolve();
  },
  deleteDoc: (ref: { path: string }) => {
    calls.deleteDoc(ref);
    return Promise.resolve();
  },
  getDoc: (ref: { path: string; id: string }) => {
    calls.getDoc(ref);
    const fixture = docFixtures.get(ref.path) ?? { exists: false, data: null };
    return Promise.resolve({
      exists: () => fixture.exists,
      data: () => fixture.data,
      id: ref.id,
      ref,
    });
  },
  getDocs: (refOrQuery: { path?: string; _group?: string }) => {
    calls.getDocs(refOrQuery);
    const path = refOrQuery.path ?? "";
    const docs = collectionFixtures.get(path) ?? [];
    return Promise.resolve({
      empty: docs.length === 0,
      docs: docs.map((d) => ({
        id: d.id,
        data: () => d.data,
        ref: { type: "doc", path: d.path, id: d.id },
      })),
    });
  },
  query: (ref: { path: string }, ..._constraints: unknown[]) => ({
    // Encode constraints into the path so `getDocs` can treat multi-constraint
    // queries as distinct fixture keys for tests that care.
    path: ref.path,
    _constraints,
  }),
  where: (field: string, op: string, value: unknown) => ({
    _type: "where",
    field,
    op,
    value,
  }),
  orderBy: (field: string, dir?: string) => ({
    _type: "orderBy",
    field,
    dir: dir ?? "asc",
  }),
  limit: (n: number) => ({ _type: "limit", n }),
  serverTimestamp: () => ({ __serverTimestamp: true }),
  Timestamp: {
    fromDate: (d: Date) => ({ __timestamp: d.toISOString() }),
  },
  arrayUnion: (...values: unknown[]) => ({ __arrayUnion: values }),
  writeBatch: () => {
    const ops: { op: string; ref: { path: string }; data?: unknown }[] = [];
    const b = {
      set: (ref: { path: string }, data: unknown) => {
        ops.push({ op: "set", ref, data });
        return b;
      },
      update: (ref: { path: string }, data: unknown) => {
        ops.push({ op: "update", ref, data });
        return b;
      },
      delete: (ref: { path: string }) => {
        ops.push({ op: "delete", ref });
        return b;
      },
      commit: () => {
        calls.batchCommit(ops);
        return Promise.resolve();
      },
    };
    return b;
  },
}));

vi.mock("./firebase", () => ({
  getFirebaseDb: () => ({ __mock_db: true }),
}));

// Import AFTER mocks register.
const {
  getScheduleRequestsForSchedule,
  getScheduleRequestsForUser,
  getShiftRequestsForSchedule,
  getShiftRequestsForUser,
  getScheduleChangeRequestsForSchedule,
  getScheduleChangeRequest,
  createScheduleRequest,
  updateScheduleRequestStatus,
  deleteScheduleRequest,
  getPendingAddRequestsForSchedule,
  getPendingInvitesForUser,
  getUserByEmail,
  triggerPushNotification,
  createShiftRequest,
  updateShiftRequestStatus,
  deleteShiftRequest,
  createScheduleChangeRequest,
  updateScheduleChangeRequestStatus,
  acceptScheduleInvite,
} = await import("./requests");

beforeEach(() => {
  for (const k of Object.keys(calls) as (keyof typeof calls)[]) {
    calls[k].mockClear();
  }
  docFixtures.clear();
  collectionFixtures.clear();
});

// =========================================================================
// READS
// =========================================================================

describe("getScheduleRequestsForSchedule", () => {
  it("returns docs from the schedule_requests collection with id populated", async () => {
    setCollectionFixture("schedule_requests", [
      {
        id: "r1",
        data: {
          is_add_request: true,
          is_join_request: false,
          schedule_name: "Test",
          request_status: "ADD_RQUEST_PENDING",
        },
      },
      {
        id: "r2",
        data: {
          is_add_request: false,
          is_join_request: true,
          schedule_name: "Test",
          request_status: "JOIN_REQUEST_ACCEPTED",
        },
      },
    ]);
    const out = await getScheduleRequestsForSchedule("sid1");
    expect(out).toHaveLength(2);
    expect(out[0].id).toBe("r1");
    expect(out[0].request_status).toBe("ADD_RQUEST_PENDING");
    expect(out[1].is_join_request).toBe(true);
  });

  it("returns [] when no requests match (no throwing)", async () => {
    const out = await getScheduleRequestsForSchedule("empty-schedule");
    expect(out).toEqual([]);
  });
});

describe("getScheduleRequestsForUser", () => {
  it("merges from_user and to_user queries, deduped by id", async () => {
    // Both queries hit the same collection path in our mock — so put two
    // overlapping docs in the fixture and expect dedupe via Map.
    setCollectionFixture("schedule_requests", [
      { id: "r1", data: { schedule_name: "A", is_add_request: true } },
      { id: "r2", data: { schedule_name: "B", is_join_request: true } },
    ]);
    const out = await getScheduleRequestsForUser("u1");
    const ids = out.map((r) => r.id).sort();
    expect(ids).toEqual(["r1", "r2"]);
  });

  it("returns [] when user has no requests", async () => {
    const out = await getScheduleRequestsForUser("nobody");
    expect(out).toEqual([]);
  });
});

describe("getShiftRequestsForSchedule", () => {
  it("fetches built_schedules first, then collectionGroup-queries shift_requests", async () => {
    setCollectionFixture("schedules/sid1/built_schedules", [
      { id: "b1", data: {} },
      { id: "b2", data: {} },
    ]);
    setCollectionFixture("__group__/shift_requests", [
      {
        id: "sr1",
        path: "schedules/sid1/built_schedules/b1/shift_requests/sr1",
        data: {
          reuqesting_employee: null,
          shift_to_change_from: { __timestamp: "2026-05-01T00:00:00Z" },
          shift_request_status: "PENDING",
        },
      },
    ]);
    const out = await getShiftRequestsForSchedule("sid1");
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe("sr1");
    expect(out[0].path).toBe(
      "schedules/sid1/built_schedules/b1/shift_requests/sr1"
    );
    expect(out[0].shift_request_status).toBe("PENDING");
  });

  it("returns [] when the schedule has no built_schedules yet", async () => {
    const out = await getShiftRequestsForSchedule("pristine-schedule");
    expect(out).toEqual([]);
  });

  it("chunks the built_schedule_ref `in` filter when > 30 builds", async () => {
    // Seed 35 built_schedules so the helper must split into 2 chunks.
    const bigBuilt: { id: string; data: Record<string, unknown> }[] = [];
    for (let i = 0; i < 35; i++) bigBuilt.push({ id: `b${i}`, data: {} });
    setCollectionFixture("schedules/sid1/built_schedules", bigBuilt);
    // Empty collectionGroup response is fine; we only care about call count.
    const out = await getShiftRequestsForSchedule("sid1");
    expect(out).toEqual([]);
    // 1 getDocs for built_schedules, 2 more for the two chunks = 3 total.
    const groupCalls = calls.getDocs.mock.calls.filter(
      (c) => (c[0] as { path?: string }).path === "__group__/shift_requests"
    );
    expect(groupCalls).toHaveLength(2);
  });
});

describe("getShiftRequestsForUser", () => {
  it("collectionGroup-queries shift_requests by reuqesting_employee", async () => {
    setCollectionFixture("__group__/shift_requests", [
      {
        id: "sr1",
        path: "schedules/sid1/built_schedules/b1/shift_requests/sr1",
        data: { shift_request_status: "ACCEPTED" },
      },
    ]);
    const out = await getShiftRequestsForUser("u1");
    expect(out).toHaveLength(1);
    expect(out[0].shift_request_status).toBe("ACCEPTED");
    expect(out[0].path).toContain("/shift_requests/");
  });

  it("returns [] when user has no shift requests", async () => {
    const out = await getShiftRequestsForUser("nobody");
    expect(out).toEqual([]);
  });
});

describe("getScheduleChangeRequestsForSchedule", () => {
  it("queries scheduleChangeRequest by scheduleId field", async () => {
    setCollectionFixture("scheduleChangeRequest", [
      {
        id: "sc1",
        data: {
          DateTime: { __timestamp: "2026-05-01T00:00:00Z" },
          Reason: "family trip",
          userId: "u1",
          status: "sent",
          scheduleId: "sid1",
        },
      },
    ]);
    const out = await getScheduleChangeRequestsForSchedule("sid1");
    expect(out).toHaveLength(1);
    expect(out[0].Reason).toBe("family trip");
    expect(out[0].status).toBe("sent");
  });

  it("returns [] when no change requests exist", async () => {
    const out = await getScheduleChangeRequestsForSchedule("no-such-schedule");
    expect(out).toEqual([]);
  });
});

// =========================================================================
// WRITES
// =========================================================================

describe("createScheduleRequest", () => {
  it("addDoc to schedule_requests with the Flutter-compatible payload", async () => {
    const id = await createScheduleRequest({
      isAddRequest: true,
      isJoinRequest: false,
      scheduleName: "My Team",
      requestStatus: "ADD_RQUEST_PENDING",
      fromUserUid: "u1",
      toUserUid: "u2",
      toUserIdentification: "u2@example.com",
      scheduleId: "sid1",
    });
    expect(id).toBe("new-doc-id");
    expect(calls.addDoc).toHaveBeenCalledTimes(1);
    const [ref, data] = calls.addDoc.mock.calls[0];
    expect(ref.path).toBe("schedule_requests");
    const payload = data as Record<string, unknown>;
    expect(payload.is_add_request).toBe(true);
    expect(payload.is_join_request).toBe(false);
    expect(payload.schedule_name).toBe("My Team");
    expect(payload.request_status).toBe("ADD_RQUEST_PENDING");
    // from_user and to_user are DocumentReferences (our mock encodes them as
    // {type: 'doc', path: 'users/u1'}).
    expect((payload.from_user as { path: string }).path).toBe("users/u1");
    expect((payload.to_user as { path: string }).path).toBe("users/u2");
    expect(payload.to_user_identification).toBe("u2@example.com");
    expect((payload.schedule_ref as { path: string }).path).toBe(
      "schedules/sid1"
    );
    expect(payload.is_read).toBe(false);
    expect(payload.created_time).toHaveProperty("__serverTimestamp");
  });

  it("leaves to_user null when toUserUid is omitted (invite by email only)", async () => {
    await createScheduleRequest({
      isAddRequest: true,
      isJoinRequest: false,
      scheduleName: "X",
      requestStatus: "ADD_RQUEST_PENDING",
      fromUserUid: "u1",
      toUserIdentification: "nobody@example.com",
      scheduleId: "sid1",
    });
    const payload = calls.addDoc.mock.calls[0][1] as Record<string, unknown>;
    expect(payload.to_user).toBeNull();
  });
});

describe("updateScheduleRequestStatus", () => {
  it("writes request_status + reviewer_uid + reviewed_at (serverTimestamp)", async () => {
    await updateScheduleRequestStatus(
      "r1",
      "ADD_REQUEST_ACCEPTED",
      "reviewer-uid"
    );
    expect(calls.updateDoc).toHaveBeenCalledTimes(1);
    const [ref, data] = calls.updateDoc.mock.calls[0];
    expect(ref.path).toBe("schedule_requests/r1");
    const payload = data as Record<string, unknown>;
    expect(payload.request_status).toBe("ADD_REQUEST_ACCEPTED");
    expect(payload.reviewer_uid).toBe("reviewer-uid");
    expect(payload.reviewed_at).toHaveProperty("__serverTimestamp");
  });

  it("accepts every valid ScheduleRequestStatus value (Flutter typo preserved)", async () => {
    const statuses = [
      "ADD_RQUEST_PENDING",
      "JOIN_REQUEST_PENDING",
      "ADD_REQUEST_ACCEPTED",
      "JOIN_REQUEST_ACCEPTED",
      "ADD_REQUEST_DECLINED",
      "JOIN_REQUEST_DECLINED",
    ] as const;
    for (const s of statuses) {
      await updateScheduleRequestStatus("r1", s, "rev");
    }
    expect(calls.updateDoc).toHaveBeenCalledTimes(statuses.length);
    const written = calls.updateDoc.mock.calls.map(
      (c) => (c[1] as { request_status: string }).request_status
    );
    expect(written).toEqual([...statuses]);
  });
});

describe("createShiftRequest", () => {
  it("addDoc to schedules/{sid}/built_schedules/{bid}/shift_requests with PENDING status", async () => {
    const from = new Date("2026-05-01T08:00:00Z");
    const to = new Date("2026-05-02T08:00:00Z");
    const id = await createShiftRequest({
      scheduleId: "sid1",
      builtScheduleId: "b1",
      requestingEmployeeUid: "u1",
      shiftToChangeFrom: from,
      shiftToChangeTo: to,
    });
    expect(id).toBe("new-doc-id");
    const [ref, data] = calls.addDoc.mock.calls[0];
    expect(ref.path).toBe(
      "schedules/sid1/built_schedules/b1/shift_requests"
    );
    const payload = data as Record<string, unknown>;
    // Flutter typo preserved
    expect(payload.reuqesting_employee).toBeDefined();
    expect((payload.reuqesting_employee as { path: string }).path).toBe(
      "users/u1"
    );
    expect((payload.shift_to_change_from as { __timestamp: string }).__timestamp).toBe(
      from.toISOString()
    );
    expect((payload.shift_to_change_to as { __timestamp: string }).__timestamp).toBe(
      to.toISOString()
    );
    expect((payload.built_schedule_ref as { path: string }).path).toBe(
      "schedules/sid1/built_schedules/b1"
    );
    expect(payload.shift_request_status).toBe("PENDING");
  });
});

describe("updateShiftRequestStatus", () => {
  it("accepts a full collectionGroup path", async () => {
    await updateShiftRequestStatus(
      "schedules/sid1/built_schedules/b1/shift_requests/sr1",
      "ACCEPTED",
      "reviewer"
    );
    expect(calls.updateDoc).toHaveBeenCalledTimes(1);
    const [ref, data] = calls.updateDoc.mock.calls[0];
    expect(ref.path).toBe(
      "schedules/sid1/built_schedules/b1/shift_requests/sr1"
    );
    const payload = data as Record<string, unknown>;
    expect(payload.shift_request_status).toBe("ACCEPTED");
    expect(payload.reviewer_uid).toBe("reviewer");
    expect(payload.reviewed_at).toHaveProperty("__serverTimestamp");
  });

  it("writes REJECETED (Flutter typo) without silently correcting it", async () => {
    await updateShiftRequestStatus(
      "schedules/sid1/built_schedules/b1/shift_requests/sr1",
      "REJECETED",
      "reviewer"
    );
    const payload = calls.updateDoc.mock.calls[0][1] as Record<string, unknown>;
    expect(payload.shift_request_status).toBe("REJECETED");
  });
});

describe("deleteShiftRequest", () => {
  it("deletes a PENDING request", async () => {
    setDocFixture(
      "schedules/sid1/built_schedules/b1/shift_requests/sr1",
      { shift_request_status: "PENDING" }
    );
    await deleteShiftRequest(
      "schedules/sid1/built_schedules/b1/shift_requests/sr1"
    );
    expect(calls.deleteDoc).toHaveBeenCalledTimes(1);
    const [ref] = calls.deleteDoc.mock.calls[0];
    expect(ref.path).toBe(
      "schedules/sid1/built_schedules/b1/shift_requests/sr1"
    );
  });

  it("throws on ACCEPTED — status transition is protected", async () => {
    setDocFixture(
      "schedules/sid1/built_schedules/b1/shift_requests/sr1",
      { shift_request_status: "ACCEPTED" }
    );
    await expect(
      deleteShiftRequest(
        "schedules/sid1/built_schedules/b1/shift_requests/sr1"
      )
    ).rejects.toThrow(/only PENDING/);
    expect(calls.deleteDoc).not.toHaveBeenCalled();
  });

  it("throws on REJECETED (Flutter typo) — still not deletable", async () => {
    setDocFixture(
      "schedules/sid1/built_schedules/b1/shift_requests/sr1",
      { shift_request_status: "REJECETED" }
    );
    await expect(
      deleteShiftRequest(
        "schedules/sid1/built_schedules/b1/shift_requests/sr1"
      )
    ).rejects.toThrow(/REJECETED/);
    expect(calls.deleteDoc).not.toHaveBeenCalled();
  });

  it("throws when the doc doesn't exist", async () => {
    missingDocFixture(
      "schedules/sid1/built_schedules/b1/shift_requests/ghost"
    );
    await expect(
      deleteShiftRequest(
        "schedules/sid1/built_schedules/b1/shift_requests/ghost"
      )
    ).rejects.toThrow(/not found/i);
  });
});

describe("createScheduleChangeRequest", () => {
  it("writes DateTime, Reason, userId, status='sent', scheduleId", async () => {
    const when = new Date("2026-06-01T00:00:00Z");
    const id = await createScheduleChangeRequest({
      scheduleId: "sid1",
      userId: "u1",
      reason: "vacation",
      dateTime: when,
    });
    expect(id).toBe("auto-id");
    expect(calls.setDoc).toHaveBeenCalledTimes(1);
    const [ref, data] = calls.setDoc.mock.calls[0];
    expect(ref.path).toBe("scheduleChangeRequest/auto-id");
    const payload = data as Record<string, unknown>;
    // Flutter field names are capitalised (DateTime, Reason) — preserve.
    expect((payload.DateTime as { __timestamp: string }).__timestamp).toBe(
      when.toISOString()
    );
    expect(payload.Reason).toBe("vacation");
    expect(payload.userId).toBe("u1");
    expect(payload.status).toBe("sent");
    expect(payload.scheduleId).toBe("sid1");
  });

  it("honours an explicit status override (e.g. 'accepted')", async () => {
    await createScheduleChangeRequest({
      scheduleId: "sid1",
      userId: "u1",
      reason: "x",
      dateTime: new Date("2026-06-01T00:00:00Z"),
      status: "accepted",
    });
    const payload = calls.setDoc.mock.calls[0][1] as Record<string, unknown>;
    expect(payload.status).toBe("accepted");
  });
});

describe("getScheduleChangeRequest", () => {
  it("reads a single scheduleChangeRequest doc by id", async () => {
    setDocFixture("scheduleChangeRequest/rc1", {
      DateTime: { __timestamp: "2026-07-01T00:00:00Z" },
      Reason: "family trip",
      userId: "u1",
      status: "sent",
      scheduleId: "sid1",
    });
    const out = await getScheduleChangeRequest("rc1");
    expect(out).not.toBeNull();
    expect(out?.id).toBe("rc1");
    expect(out?.Reason).toBe("family trip");
    expect(out?.status).toBe("sent");
  });

  it("returns null when the doc is missing", async () => {
    missingDocFixture("scheduleChangeRequest/ghost");
    const out = await getScheduleChangeRequest("ghost");
    expect(out).toBeNull();
  });
});

describe("updateScheduleChangeRequestStatus", () => {
  it("writes status + reviewer_uid + resolved_at (serverTimestamp) for 'accepted'", async () => {
    await updateScheduleChangeRequestStatus("rc1", "accepted", "reviewer-uid");
    expect(calls.updateDoc).toHaveBeenCalledTimes(1);
    const [ref, data] = calls.updateDoc.mock.calls[0];
    expect(ref.path).toBe("scheduleChangeRequest/rc1");
    const payload = data as Record<string, unknown>;
    expect(payload.status).toBe("accepted");
    expect(payload.reviewer_uid).toBe("reviewer-uid");
    expect(payload.resolved_at).toHaveProperty("__serverTimestamp");
  });

  it("also works for 'declined' (Flutter's reject value)", async () => {
    await updateScheduleChangeRequestStatus("rc1", "declined", "reviewer");
    const payload = calls.updateDoc.mock.calls[0][1] as Record<string, unknown>;
    expect(payload.status).toBe("declined");
  });
});

// =========================================================================
// Employee-invite helpers (B4) — added for feat/round3-employee-invite.
// =========================================================================

describe("deleteScheduleRequest", () => {
  it("deletes schedule_requests/{id} (Flutter employee_list_widget.dart:568)", async () => {
    await deleteScheduleRequest("req-9");
    expect(calls.deleteDoc).toHaveBeenCalledTimes(1);
    const [ref] = calls.deleteDoc.mock.calls[0];
    expect(ref.path).toBe("schedule_requests/req-9");
  });
});

describe("getPendingAddRequestsForSchedule", () => {
  it("returns only add-requests still ADD_RQUEST_PENDING", async () => {
    setCollectionFixture("schedule_requests", [
      {
        id: "p1",
        data: {
          is_add_request: true,
          request_status: "ADD_RQUEST_PENDING",
          to_user_identification: "a@x.com",
        },
      },
      {
        id: "p2",
        data: { is_add_request: true, request_status: "ADD_REQUEST_ACCEPTED" },
      },
      {
        id: "p3",
        data: { is_join_request: true, request_status: "JOIN_REQUEST_PENDING" },
      },
    ]);
    const out = await getPendingAddRequestsForSchedule("sid1");
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe("p1");
  });
});

describe("getPendingInvitesForUser", () => {
  it("returns only pending add-requests TARGETING the user (to_user)", async () => {
    // Mock `doc(db,'users',uid)` yields { path: 'users/<uid>' }; the helper
    // matches r.to_user.path === `users/${uid}`.
    setCollectionFixture("schedule_requests", [
      {
        id: "i1",
        data: {
          is_add_request: true,
          request_status: "ADD_RQUEST_PENDING",
          to_user: { type: "doc", path: "users/u1", id: "u1" },
          to_user_identification: "u1@x.com",
        },
      },
      {
        // accepted — not actionable
        id: "i2",
        data: {
          is_add_request: true,
          request_status: "ADD_REQUEST_ACCEPTED",
          to_user: { type: "doc", path: "users/u1", id: "u1" },
        },
      },
      {
        // authored by a different target — must be filtered out
        id: "i3",
        data: {
          is_add_request: true,
          request_status: "ADD_RQUEST_PENDING",
          to_user: { type: "doc", path: "users/other", id: "other" },
        },
      },
      {
        // email-only invite (to_user null) — not actionable by an account
        id: "i4",
        data: {
          is_add_request: true,
          request_status: "ADD_RQUEST_PENDING",
          to_user: null,
        },
      },
    ]);
    const out = await getPendingInvitesForUser("u1");
    expect(out.map((r) => r.id)).toEqual(["i1"]);
  });
});

describe("getUserByEmail", () => {
  it("returns the user when an account exists for the email", async () => {
    setCollectionFixture("users", [
      { id: "uXYZ", data: { email: "found@x.com", display_name: "Found User" } },
    ]);
    const out = await getUserByEmail("found@x.com");
    expect(out).not.toBeNull();
    expect(out?.uid).toBe("uXYZ");
    expect(out?.email).toBe("found@x.com");
    expect(out?.display_name).toBe("Found User");
    expect(out?.ref.path).toBe("users/uXYZ");
  });

  it("returns null when no account exists (email-only invite path)", async () => {
    const out = await getUserByEmail("nobody@x.com");
    expect(out).toBeNull();
  });
});

describe("triggerPushNotification", () => {
  it("writes one ff_user_push_notifications doc with comma-joined user_refs", async () => {
    await triggerPushNotification({
      notificationTitle: "Hi",
      notificationText: "Body",
      toUserUids: ["a", "b"],
      fromUserUid: "mgr",
      parameterData: { shouldDisplayScheduleRequest: true },
    });
    expect(calls.addDoc).toHaveBeenCalledTimes(1);
    const [ref, data] = calls.addDoc.mock.calls[0];
    expect(ref.path).toBe("ff_user_push_notifications");
    const p = data as Record<string, unknown>;
    expect(p.notification_title).toBe("Hi");
    expect(p.user_refs).toBe("users/a,users/b");
    expect(p.initial_page_name).toBe("Home");
    expect(JSON.parse(p.parameter_data as string)).toEqual({
      shouldDisplayScheduleRequest: true,
    });
    expect(p.timestamp).toHaveProperty("__serverTimestamp");
  });

  it("no-ops when there are no recipients (Flutter guard line 77-79)", async () => {
    await triggerPushNotification({
      notificationTitle: "Hi",
      notificationText: "Body",
      toUserUids: [],
      fromUserUid: "mgr",
    });
    expect(calls.addDoc).not.toHaveBeenCalled();
  });

  it("no-ops when title or body is empty", async () => {
    await triggerPushNotification({
      notificationTitle: "",
      notificationText: "Body",
      toUserUids: ["a"],
      fromUserUid: "mgr",
    });
    expect(calls.addDoc).not.toHaveBeenCalled();
  });
});

// ============================================================================
// acceptScheduleInvite — the Flutter-parity 4-write accept batch
// (schedule_request_widget.dart ~880-1010). Regression guard for the
// 2026-06-11 P0: accept used to flip status only — never membership.
// ============================================================================

describe("acceptScheduleInvite", () => {
  const scheduleRef = { type: "doc", path: "schedules/s1", id: "s1" };
  const baseReq = {
    id: "req-1",
    is_add_request: true,
    is_join_request: false,
    schedule_name: "Inv2 Rota",
    request_status: "ADD_RQUEST_PENDING",
    from_user: null,
    to_user: { type: "doc", path: "users/emp-1", id: "emp-1" },
    to_user_identification: "emp@example.com",
    created_time: null,
    schedule_ref: scheduleRef,
    is_read: true,
  };
  const profile = {
    uid: "emp-1",
    displayName: "Inv2 Employee",
    email: "emp@example.com",
    phone: "+972500000000",
  };

  it("commits all four Flutter writes atomically with exact field names", async () => {
    setCollectionFixture("chats", [
      { id: "c1", data: { schedule_ref: scheduleRef, users: [] } },
    ]);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await acceptScheduleInvite(baseReq as any, profile);

    expect(calls.batchCommit).toHaveBeenCalledTimes(1);
    const ops = calls.batchCommit.mock.calls[0][0] as {
      op: string;
      ref: { path: string };
      data: Record<string, unknown>;
    }[];
    expect(ops).toHaveLength(4);

    // (1) status update + web audit fields
    expect(ops[0].op).toBe("update");
    expect(ops[0].ref.path).toBe("schedule_requests/req-1");
    expect(ops[0].data.request_status).toBe("ADD_REQUEST_ACCEPTED");
    expect(ops[0].data.reviewer_uid).toBe("emp-1");

    // (2) users/{uid}/schedules_involved doc — 21-slot all-false priorities
    expect(ops[1].op).toBe("set");
    expect(ops[1].ref.path).toBe("users/emp-1/schedules_involved/auto-id");
    expect(ops[1].data.schedules_collection_ref).toBe(scheduleRef);
    expect(ops[1].data.schedule_name).toBe("Inv2 Rota");
    expect(ops[1].data.priorities_private).toHaveLength(21);
    expect(
      (ops[1].data.priorities_private as boolean[]).every((v) => v === false)
    ).toBe(true);

    // (3) schedule employees[] arrayUnion — exact Flutter struct keys
    expect(ops[2].op).toBe("update");
    expect(ops[2].ref.path).toBe("schedules/s1");
    const union = ops[2].data.employees as { __arrayUnion: unknown[] };
    const entry = union.__arrayUnion[0] as Record<string, unknown>;
    expect(entry).toEqual({
      employee_name: "Inv2 Employee",
      role: { is_worker: true },
      employee_phone: "+972500000000",
      user_ref: expect.objectContaining({ path: "users/emp-1" }),
      employee_email: "emp@example.com",
    });

    // (4) schedule chat users arrayUnion — the users/{uid} REFERENCE
    // (Flutter-created schedule chats store references, not uid strings)
    expect(ops[3].op).toBe("update");
    expect(ops[3].ref.path).toBe("chats/c1");
    const chatUnion = ops[3].data.users as { __arrayUnion: unknown[] };
    expect(chatUnion.__arrayUnion[0]).toEqual(
      expect.objectContaining({ path: "users/emp-1" })
    );
  });

  it("skips the chat write (3 ops) when the schedule has no chat doc", async () => {
    setCollectionFixture("chats", []);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await acceptScheduleInvite(baseReq as any, profile);

    const ops = calls.batchCommit.mock.calls[0][0] as { ref: { path: string } }[];
    expect(ops).toHaveLength(3);
    expect(ops.map((o) => o.ref.path)).toEqual([
      "schedule_requests/req-1",
      "users/emp-1/schedules_involved/auto-id",
      "schedules/s1",
    ]);
  });

  it("throws (and commits nothing) when the invite has no schedule_ref", async () => {
    await expect(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      acceptScheduleInvite({ ...baseReq, schedule_ref: null } as any, profile)
    ).rejects.toThrow(/schedule_ref/);
    expect(calls.batchCommit).not.toHaveBeenCalled();
  });
});
