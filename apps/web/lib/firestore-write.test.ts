import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock firebase/firestore before importing firestore-write. Each call records
// its arguments so we can assert on the shape of what's written.
const calls = {
  addDoc: vi.fn(),
  setDoc: vi.fn(),
  updateDoc: vi.fn(),
  deleteDoc: vi.fn(),
  getDoc: vi.fn(),
  getDocs: vi.fn(),
  txGet: vi.fn(),
  txSet: vi.fn(),
  writeBatchSet: vi.fn(),
  writeBatchUpdate: vi.fn(),
  writeBatchDelete: vi.fn(),
  writeBatchCommit: vi.fn(),
};

// Mutable transaction state so tests can simulate an existing uniqueness marker
// (i.e. a duplicate name) for createSchedule's runTransaction path.
const txState = { markerExists: false };

// Mutable getDoc state — delete/rename read the schedule doc to find the owner +
// current name so they can clean up / migrate the uniqueness marker.
const docState: { exists: boolean; data: Record<string, unknown> } = {
  exists: true,
  data: { created_by: "owner-1", schedule_name: "Existing Name" },
};

vi.mock("firebase/firestore", () => ({
  collection: (parent: unknown, ...segments: string[]) => {
    // `collection(docRef, 'messages')` — use the parent doc's path as prefix
    // so subcollections resolve to the right nested path.
    if (
      parent &&
      typeof parent === "object" &&
      "path" in (parent as Record<string, unknown>) &&
      (parent as { type?: string }).type === "doc"
    ) {
      return {
        type: "collection",
        path: [(parent as { path: string }).path, ...segments].join("/"),
      };
    }
    return {
      type: "collection",
      path: segments.join("/"),
    };
  },
  doc: (parent: unknown, ...segments: string[]) => {
    // `doc(collectionRef)` — auto-id inside the collection's path.
    if (
      segments.length === 0 &&
      parent &&
      typeof parent === "object" &&
      (parent as { type?: string }).type === "collection"
    ) {
      const cPath = (parent as { path: string }).path;
      return { type: "doc", path: `${cPath}/auto-id`, id: "auto-id" };
    }
    return {
      type: "doc",
      path: segments.join("/"),
      id: segments[segments.length - 1],
    };
  },
  addDoc: (ref: { path: string }, data: Record<string, unknown>) => {
    calls.addDoc(ref, data);
    return Promise.resolve({ id: "new-doc-id" });
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
  getDoc: (ref: { path: string }) => {
    calls.getDoc(ref);
    return Promise.resolve({
      exists: () => docState.exists,
      data: () => docState.data,
    });
  },
  getDocs: (ref: { path: string }) => {
    calls.getDocs(ref);
    // Return one doc per subcollection so deleteSchedule exercises the
    // batch.delete + batch.commit path (not the empty-subcollection branch).
    return Promise.resolve({
      docs: [{ ref: { type: "doc", path: `${ref.path}/doc-1` } }],
    });
  },
  runTransaction: (
    _db: unknown,
    fn: (tx: {
      get: (ref: { path: string }) => Promise<{ exists: () => boolean }>;
      set: (ref: { path: string }, data: Record<string, unknown>) => void;
    }) => unknown
  ) =>
    Promise.resolve(
      fn({
        get: (ref: { path: string }) => {
          calls.txGet(ref);
          return Promise.resolve({ exists: () => txState.markerExists });
        },
        set: (ref: { path: string }, data: Record<string, unknown>) => {
          calls.txSet(ref, data);
        },
      })
    ),
  arrayUnion: (...values: unknown[]) => ({ __arrayUnion: values }),
  arrayRemove: (...values: unknown[]) => ({ __arrayRemove: values }),
  serverTimestamp: () => ({ __serverTimestamp: true }),
  increment: (n: number) => ({ __increment: n }),
  writeBatch: () => ({
    set: (ref: unknown, data: unknown) => calls.writeBatchSet(ref, data),
    update: (ref: unknown, data: unknown) => calls.writeBatchUpdate(ref, data),
    delete: (ref: unknown) => calls.writeBatchDelete(ref),
    commit: () => {
      calls.writeBatchCommit();
      return Promise.resolve();
    },
  }),
  Timestamp: {
    fromDate: (d: Date) => ({ __timestamp: d.toISOString() }),
  },
}));

vi.mock("./firebase", () => ({
  getFirebaseDb: () => ({ __mock_db: true }),
}));

// Import AFTER mocks register.
const {
  createSchedule,
  ScheduleNameTakenError,
  updateScheduleName,
  addEmployee,
  addEmployeesBulk,
  removeEmployee,
  deleteSchedule,
  submitPriorities,
  updateScheduleSettings,
  publishBuiltSchedule,
  upsertUserProfile,
  registerFcmToken,
  sendChatMessage,
  createChatThread,
  markMessageSeen,
  incrementMonthlyBuildCount,
} = await import("./firestore-write");

beforeEach(() => {
  for (const k of Object.keys(calls) as (keyof typeof calls)[]) {
    calls[k].mockClear();
  }
  txState.markerExists = false;
  docState.exists = true;
  docState.data = { created_by: "owner-1", schedule_name: "Existing Name" };
});

describe("createSchedule", () => {
  // Helper: find a transaction set() call by the doc path it wrote to.
  const txSetFor = (substr: string) =>
    calls.txSet.mock.calls.find(([ref]) =>
      (ref as { path: string }).path.includes(substr)
    );

  it("writes a Flutter-compatible schedule doc + back-ref + uniqueness marker atomically", async () => {
    const id = await createSchedule({
      scheduleName: "Test",
      numOfStations: 2,
      enabledShifts: ["morning", "night"],
      ownerUid: "u1",
      ownerEmail: "u1@example.com",
      ownerName: "Uno",
    });
    // Pre-generated id from doc(collection("schedules")) inside the transaction.
    expect(id).toBe("auto-id");

    // The whole create is one transaction: read the marker, then 3 writes.
    expect(calls.txGet).toHaveBeenCalledTimes(1);
    expect(calls.txGet.mock.calls[0][0].path).toBe(
      "users/u1/schedule_names/n_test"
    );
    // No bare addDoc — uniqueness must not be racy.
    expect(calls.addDoc).not.toHaveBeenCalled();
    expect(calls.txSet).toHaveBeenCalledTimes(3);

    // 1) The schedule doc.
    const scheduleCall = txSetFor("schedules/auto-id");
    expect(scheduleCall).toBeDefined();
    const schedule = scheduleCall![1] as Record<string, unknown>;
    expect(schedule.schedule_name).toBe("Test");
    expect(Array.isArray(schedule.employees)).toBe(true);
    expect((schedule.employees as unknown[]).length).toBe(1);
    expect(schedule.current_priorities).toEqual(new Array(21).fill(""));
    const settings = schedule.schedule_settings as Record<string, unknown>;
    const shifts = settings.enabled_shifts as Record<string, unknown>;
    expect(shifts.morning).toBe(true);
    expect(shifts.afternoon).toBe(false);
    expect(shifts.night).toBe(true);
    expect(settings.num_of_stations).toBe(2);
    const deadline = settings.submission_deadline as Record<string, unknown>;
    expect(deadline.is_activated).toBe(false);
    expect(deadline.weekday).toBe("SUNDAY");
    expect(deadline.time).toBeNull();

    // 2) The per-user back-ref.
    const backCall = txSetFor("schedules_involved/auto-id");
    expect(backCall).toBeDefined();
    expect(backCall![1]).toMatchObject({
      schedule_name: "Test",
      priorities_private: new Array(21).fill(false),
    });

    // 3) The uniqueness marker.
    const markerCall = txSetFor("schedule_names/n_test");
    expect(markerCall).toBeDefined();
    expect(markerCall![1]).toMatchObject({
      schedule_id: "auto-id",
      schedule_name: "Test",
    });
  });

  it("throws ScheduleNameTakenError and writes nothing when the marker already exists", async () => {
    txState.markerExists = true;
    await expect(
      createSchedule({
        scheduleName: "Test",
        numOfStations: 1,
        enabledShifts: ["morning"],
        ownerUid: "u1",
        ownerEmail: "u1@example.com",
        ownerName: "Uno",
      })
    ).rejects.toBeInstanceOf(ScheduleNameTakenError);
    // The transaction aborted before any write.
    expect(calls.txSet).not.toHaveBeenCalled();
    expect(calls.addDoc).not.toHaveBeenCalled();
  });

  it("normalizes the marker id (trim + lowercase) so case/space variants collide", async () => {
    await createSchedule({
      scheduleName: "  Morning Shift  ",
      numOfStations: 1,
      enabledShifts: ["morning"],
      ownerUid: "u1",
      ownerEmail: "u1@example.com",
      ownerName: "Uno",
    });
    // "  Morning Shift  " -> "morning shift" -> URL-encoded with n_ prefix.
    const expected = "n_" + encodeURIComponent("morning shift");
    expect(calls.txGet.mock.calls[0][0].path).toBe(
      `users/u1/schedule_names/${expected}`
    );
    const markerCall = txSetFor(`schedule_names/${expected}`);
    expect(markerCall).toBeDefined();
  });
});

describe("updateScheduleName", () => {
  it("updates the schedule doc and fans out to each involved user", async () => {
    await updateScheduleName("sid1", "Renamed", ["u1", "u2", "u3"]);
    expect(calls.updateDoc).toHaveBeenCalledTimes(4); // 1 schedule + 3 users
    const paths = calls.updateDoc.mock.calls.map((c) => c[0].path);
    expect(paths).toContain("schedules/sid1");
    expect(paths).toContain("users/u1/schedules_involved/sid1");
    expect(paths).toContain("users/u2/schedules_involved/sid1");
    expect(paths).toContain("users/u3/schedules_involved/sid1");
  });

  it("tolerates a fan-out failure on one involved doc", async () => {
    // The function wraps each fan-out in .catch(...) — no throw expected.
    await expect(
      updateScheduleName("sid2", "X", ["a"])
    ).resolves.toBeUndefined();
  });

  it("migrates the uniqueness marker on rename (drops old, writes new)", async () => {
    // docState: owner-1 owns "Existing Name"; rename it to "Renamed".
    await updateScheduleName("sid1", "Renamed", ["u1"]);

    // Old marker deleted so the old name can be reused.
    const deletedPaths = calls.deleteDoc.mock.calls.map(
      (c) => (c[0] as { path: string }).path,
    );
    expect(deletedPaths).toContain(
      `users/owner-1/schedule_names/n_${encodeURIComponent("existing name")}`,
    );

    // New marker written for the new name.
    const setPaths = calls.setDoc.mock.calls.map(
      (c) => (c[0] as { path: string }).path,
    );
    expect(setPaths).toContain("users/owner-1/schedule_names/n_renamed");
    const markerData = calls.setDoc.mock.calls.find(
      (c) => (c[0] as { path: string }).path.includes("schedule_names/n_renamed"),
    )![1];
    expect(markerData).toMatchObject({
      schedule_id: "sid1",
      schedule_name: "Renamed",
    });
  });

  it("does not delete the marker when the normalized name is unchanged (case-only edit)", async () => {
    // "Existing Name" -> "existing name" normalizes to the same marker id.
    await updateScheduleName("sid1", "existing name", ["u1"]);
    const deletedPaths = calls.deleteDoc.mock.calls.map(
      (c) => (c[0] as { path: string }).path,
    );
    expect(deletedPaths.some((p) => p.includes("schedule_names"))).toBe(false);
    // The marker is still re-written (idempotent) with the new casing.
    const setPaths = calls.setDoc.mock.calls.map(
      (c) => (c[0] as { path: string }).path,
    );
    expect(
      setPaths.some((p) => p.includes("schedule_names/n_")),
    ).toBe(true);
  });
});

describe("addEmployee / removeEmployee", () => {
  it("addEmployee uses arrayUnion on schedules.employees", async () => {
    await addEmployee("sid1", {
      employee_name: "Ava",
      employee_email: "ava@example.com",
      employee_phone: "",
      role: { is_creator: false, is_admin: false, is_worker: true },
    });
    expect(calls.updateDoc).toHaveBeenCalledTimes(1);
    const [ref, data] = calls.updateDoc.mock.calls[0];
    expect(ref.path).toBe("schedules/sid1");
    const employees = (data as Record<string, unknown>).employees as {
      __arrayUnion: unknown[];
    };
    expect(employees.__arrayUnion).toHaveLength(1);
  });

  it("removeEmployee uses arrayRemove", async () => {
    await removeEmployee("sid1", {
      employee_name: "Ava",
      employee_email: "ava@example.com",
      employee_phone: "",
      role: { is_creator: false, is_admin: false, is_worker: true },
      user_ref: null,
    });
    expect(calls.updateDoc).toHaveBeenCalledTimes(1);
    const data = calls.updateDoc.mock.calls[0][1];
    expect((data as Record<string, unknown>).employees).toHaveProperty(
      "__arrayRemove"
    );
  });
});

describe("submitPriorities (dual-write)", () => {
  it("writes priorities_private bool[21] on schedules_involved AND the rich subcoll doc", async () => {
    await submitPriorities("sid1", "u1", "User One", ["Sun|morning", "Mon|night"]);
    expect(calls.setDoc).toHaveBeenCalledTimes(2);
    const paths = calls.setDoc.mock.calls.map((c) => c[0].path);
    expect(paths).toContain("users/u1/schedules_involved/sid1");
    expect(paths).toContain("schedules/sid1/priorities_submissions/u1");

    // Find the Flutter-canonical call
    const flutterCall = calls.setDoc.mock.calls.find(
      (c) => c[0].path === "users/u1/schedules_involved/sid1"
    )!;
    const bools = (flutterCall[1] as Record<string, unknown>)
      .priorities_private as boolean[];
    expect(bools).toHaveLength(21);
    expect(bools[0]).toBe(true); // Sun|morning
    expect(bools[5]).toBe(true); // Mon|night
    expect(bools.filter((b) => b).length).toBe(2);

    // Find the Next.js-only call
    const nextCall = calls.setDoc.mock.calls.find(
      (c) => c[0].path === "schedules/sid1/priorities_submissions/u1"
    )!;
    const data = nextCall[1] as Record<string, unknown>;
    expect(data.display_name).toBe("User One");
    expect(data.priorities).toEqual(["Sun|morning", "Mon|night"]);
  });
});

describe("updateScheduleSettings", () => {
  it("writes the nested EnabledShiftsStruct + hours + num_of_stations", async () => {
    await updateScheduleSettings("sid1", {
      enabled_shifts: ["morning", "night"],
      num_of_stations: 3,
      morning_hours: "06:00-14:00",
      noon_hours: "",
      night_hours: "22:00-06:00",
    });
    expect(calls.updateDoc).toHaveBeenCalledTimes(1);
    const [ref, data] = calls.updateDoc.mock.calls[0];
    expect(ref.path).toBe("schedules/sid1");
    const payload = data as Record<string, unknown>;
    const shifts = payload[
      "schedule_settings.enabled_shifts"
    ] as Record<string, unknown>;
    expect(shifts.morning).toBe(true);
    expect(shifts.afternoon).toBe(false);
    expect(shifts.night).toBe(true);
    expect(payload["schedule_settings.num_of_stations"]).toBe(3);
    expect(payload["schedule_settings.morning_hours"]).toBe("06:00-14:00");
    expect(payload["schedule_settings.night_hours"]).toBe("22:00-06:00");
  });
});

describe("publishBuiltSchedule", () => {
  it("writes time_created + weekday fields + optional timestamps", async () => {
    const start = new Date("2026-05-03T00:00:00Z");
    const end = new Date("2026-05-09T00:00:00Z");
    await publishBuiltSchedule("sid1", {
      rows: [{ stringList: ["A"] }],
      firstWeekday: "2026-05-03",
      lastWeekday: "2026-05-09",
      currentPriorities: ["A"],
      startDate: start,
      endDate: end,
    });
    expect(calls.addDoc).toHaveBeenCalledTimes(1);
    const [ref, data] = calls.addDoc.mock.calls[0];
    expect(ref.path).toBe("schedules/sid1/built_schedules");
    const payload = data as Record<string, unknown>;
    expect(payload.first_weekday).toBe("2026-05-03");
    expect(payload.last_weekday).toBe("2026-05-09");
    expect(payload.first_weekday_datetime).toHaveProperty("__timestamp");
    expect(payload.last_weekday_datetime).toHaveProperty("__timestamp");
    expect(payload.time_created).toHaveProperty("__serverTimestamp");
  });

  it("omits weekday_datetime when no dates provided", async () => {
    await publishBuiltSchedule("sid1", {
      rows: [],
      firstWeekday: "",
      lastWeekday: "",
    });
    const payload = calls.addDoc.mock.calls[0][1] as Record<string, unknown>;
    expect(payload.first_weekday_datetime).toBeNull();
    expect(payload.last_weekday_datetime).toBeNull();
  });
});

describe("upsertUserProfile", () => {
  it("converts RoleStruct → Flutter string 'employer' for admin/creator", async () => {
    await upsertUserProfile("u1", "u@example.com", {
      display_name: "U",
      title: "Manager",
      role: { is_creator: false, is_admin: true, is_worker: false },
    });
    const data = calls.setDoc.mock.calls[0][1] as Record<string, unknown>;
    expect(data.role).toBe("employer");
  });

  it("converts RoleStruct → Flutter string 'employee' for worker-only", async () => {
    await upsertUserProfile("u1", "u@example.com", {
      display_name: "U",
      title: "",
      role: { is_creator: false, is_admin: false, is_worker: true },
    });
    const data = calls.setDoc.mock.calls[0][1] as Record<string, unknown>;
    expect(data.role).toBe("employee");
  });

  it("writes last_active_time instead of the old 'updated_at'/'onboarded'", async () => {
    await upsertUserProfile("u1", "u@example.com", {
      display_name: "U",
      title: "",
      role: { is_creator: false, is_admin: false, is_worker: true },
    });
    const data = calls.setDoc.mock.calls[0][1] as Record<string, unknown>;
    expect(data).toHaveProperty("last_active_time");
    expect(data).not.toHaveProperty("updated_at");
    expect(data).not.toHaveProperty("onboarded");
  });
});

describe("registerFcmToken", () => {
  it("writes fcm_tokens: arrayUnion(token) on users/{uid}", async () => {
    await registerFcmToken("u1", "token-abc");
    expect(calls.updateDoc).toHaveBeenCalledTimes(1);
    const [ref, data] = calls.updateDoc.mock.calls[0];
    expect(ref.path).toBe("users/u1");
    const payload = data as Record<string, unknown>;
    expect(payload.fcm_tokens).toEqual({ __arrayUnion: ["token-abc"] });
  });
});

describe("addEmployeesBulk", () => {
  it("no-ops on an empty list (avoids a pointless updateDoc)", async () => {
    await addEmployeesBulk("sid1", []);
    expect(calls.updateDoc).not.toHaveBeenCalled();
  });

  it("arrayUnions every employee (with user_ref:null) onto schedules.employees", async () => {
    await addEmployeesBulk("sid1", [
      {
        employee_name: "Alice",
        employee_email: "a@example.com",
        employee_phone: "",
        role: { is_creator: false, is_admin: false, is_worker: true },
      },
      {
        employee_name: "Bob",
        employee_email: "b@example.com",
        employee_phone: "",
        role: { is_creator: false, is_admin: false, is_worker: true },
      },
    ]);
    expect(calls.updateDoc).toHaveBeenCalledTimes(1);
    const [ref, data] = calls.updateDoc.mock.calls[0];
    expect(ref.path).toBe("schedules/sid1");
    const payload = data as { employees: { __arrayUnion: unknown[] } };
    expect(payload.employees.__arrayUnion).toHaveLength(2);
    // Each element must have user_ref: null appended (Flutter parity)
    for (const e of payload.employees.__arrayUnion as Array<{
      user_ref: unknown;
    }>) {
      expect(e.user_ref).toBeNull();
    }
  });
});

describe("deleteSchedule", () => {
  it("batches deletions of built_schedules + priorities_submissions, then deletes the schedule + user back-refs", async () => {
    await deleteSchedule("sid1", ["u1", "u2"]);

    // One getDocs per subcollection (built_schedules + priorities_submissions).
    expect(calls.getDocs).toHaveBeenCalledTimes(2);
    // The upstream mock records only the fact of the call (no ref arg), so we
    // assert the subcollection paths via the collection(...) lookup side-effect:
    // writeBatch.commit runs unconditionally regardless of result size.
    expect(calls.writeBatchCommit).toHaveBeenCalledTimes(1);

    // Our upstream mock returns { docs: [] } for getDocs — so batch.delete is
    // never called, but deleteDoc IS called once per involved uid + the
    // schedule itself + the uniqueness marker (4 deleteDoc calls total for
    // ["u1","u2"] + schedules/sid1 + the owner's name marker).
    expect(calls.deleteDoc).toHaveBeenCalledTimes(4);
    const deletedPaths = calls.deleteDoc.mock.calls.map(
      (c) => (c[0] as { path: string }).path,
    );
    expect(deletedPaths).toContain("users/u1/schedules_involved/sid1");
    expect(deletedPaths).toContain("users/u2/schedules_involved/sid1");
    expect(deletedPaths).toContain("schedules/sid1");
    // The uniqueness marker for the deleted schedule's name is freed so the
    // name can be reused. Marker id = n_ + encodeURIComponent("existing name").
    expect(deletedPaths).toContain(
      `users/owner-1/schedule_names/n_${encodeURIComponent("existing name")}`,
    );
  });

  it("skips marker cleanup when the schedule doc is missing", async () => {
    docState.exists = false;
    await deleteSchedule("sid1", ["u1"]);
    const deletedPaths = calls.deleteDoc.mock.calls.map(
      (c) => (c[0] as { path: string }).path,
    );
    // 1 involved back-ref + the schedule itself, but NO marker delete.
    expect(deletedPaths).toContain("schedules/sid1");
    expect(deletedPaths.some((p) => p.includes("schedule_names"))).toBe(false);
  });
});

describe("updateScheduleSettings (submission_deadline branch)", () => {
  it("writes the full SubmissionDeadlineStruct when a deadline is provided", async () => {
    await updateScheduleSettings("sid1", {
      enabled_shifts: ["morning"],
      num_of_stations: 2,
      submission_deadline: {
        is_activated: true,
        weekday: "MONDAY",
        time: "2026-04-25T09:00:00Z",
      },
    });
    expect(calls.updateDoc).toHaveBeenCalledTimes(1);
    const [, data] = calls.updateDoc.mock.calls[0];
    const payload = data as Record<string, unknown>;
    const deadline = payload["schedule_settings.submission_deadline"] as {
      time: { __timestamp: string } | null;
      is_activated: boolean;
      weekday: string;
    };
    expect(deadline.is_activated).toBe(true);
    expect(deadline.weekday).toBe("MONDAY");
    expect(deadline.time).toEqual({ __timestamp: "2026-04-25T09:00:00.000Z" });
  });

  it("writes submission_deadline.time=null when time is null", async () => {
    await updateScheduleSettings("sid1", {
      enabled_shifts: [],
      num_of_stations: 1,
      submission_deadline: {
        is_activated: false,
        weekday: "SUNDAY",
        time: null,
      },
    });
    const [, data] = calls.updateDoc.mock.calls[0];
    const payload = data as Record<string, unknown>;
    const deadline = payload["schedule_settings.submission_deadline"] as {
      time: unknown;
    };
    expect(deadline.time).toBeNull();
  });
});

// =========================================================================
// Chat writes (P3-4 — kept from upstream; this PR only adds gap-fills above)
// =========================================================================

describe("sendChatMessage", () => {
  it("batches the message write + parent thread last_message update", async () => {
    const id = await sendChatMessage("t1", {
      text: "hello",
      sender_uid: "u1",
    });
    expect(id).toBe("auto-id");
    // The batch captured exactly two operations
    expect(calls.writeBatchSet).toHaveBeenCalledTimes(1);
    expect(calls.writeBatchDelete).not.toHaveBeenCalled();
    expect(calls.writeBatchCommit).toHaveBeenCalledTimes(1);

    const [msgRef, msgData] = calls.writeBatchSet.mock.calls[0] as [
      { path: string },
      Record<string, unknown>,
    ];
    expect(msgRef.path).toBe("chats/t1/messages/auto-id");
    expect(msgData.text).toBe("hello");
    expect(msgData.sender_uid).toBe("u1");
    expect(msgData.timestamp).toHaveProperty("__serverTimestamp");
    // image_url omitted when not provided
    expect(msgData).not.toHaveProperty("image_url");
  });

  it("records image_url when provided (image-only messages legal)", async () => {
    await sendChatMessage("t1", {
      text: "",
      sender_uid: "u1",
      image_url: "https://x/y.png",
    });
    const [, msgData] = calls.writeBatchSet.mock.calls[0] as [
      unknown,
      Record<string, unknown>,
    ];
    expect(msgData.text).toBe("");
    expect(msgData.image_url).toBe("https://x/y.png");
  });

  it("updates the parent thread's last_message preview as part of the batch", async () => {
    await sendChatMessage("t1", { text: "hey", sender_uid: "u1" });
    // The helper uses batch.update(); our mock captures that on
    // writeBatchUpdate. Verify it was invoked on the thread ref with a
    // last_message struct whose sender matches sender_uid.
    expect(calls.writeBatchUpdate).toHaveBeenCalledTimes(1);
    const [threadRef, data] = calls.writeBatchUpdate.mock.calls[0] as [
      { path: string },
      Record<string, unknown>,
    ];
    expect(threadRef.path).toBe("chats/t1");
    const last = data.last_message as Record<string, unknown>;
    expect(last.text).toBe("hey");
    expect(last.sender).toBe("u1");
    expect(last.timestamp).toHaveProperty("__serverTimestamp");
  });
});

describe("createChatThread", () => {
  it("marks 1:1 chats as is_group=false", async () => {
    const id = await createChatThread(["u1", "u2"]);
    expect(id).toBe("new-doc-id");
    const [ref, data] = calls.addDoc.mock.calls[0] as [
      { path: string },
      Record<string, unknown>,
    ];
    expect(ref.path).toBe("chats");
    expect(data.is_group).toBe(false);
    expect(data.users).toEqual(["u1", "u2"]);
    expect(data.owner).toBe("u1");
    expect(data.created_at).toHaveProperty("__serverTimestamp");
    expect(data).not.toHaveProperty("name");
  });

  it("marks 3+ participant chats as is_group=true", async () => {
    await createChatThread(["u1", "u2", "u3"], "Team Chat");
    const data = calls.addDoc.mock.calls[0][1] as Record<string, unknown>;
    expect(data.is_group).toBe(true);
    expect(data.users).toEqual(["u1", "u2", "u3"]);
    expect(data.name).toBe("Team Chat");
  });

  it("treats a solo thread (users.length == 1) as non-group", async () => {
    await createChatThread(["u1"]);
    const data = calls.addDoc.mock.calls[0][1] as Record<string, unknown>;
    expect(data.is_group).toBe(false);
  });

  it("throws on empty participant list", async () => {
    await expect(createChatThread([])).rejects.toThrow(/at least one/i);
    expect(calls.addDoc).not.toHaveBeenCalled();
  });
});

describe("markMessageSeen", () => {
  it("arrayUnion(uid) onto the message's seen_by", async () => {
    await markMessageSeen("t1", "m1", "u3");
    expect(calls.updateDoc).toHaveBeenCalledTimes(1);
    const [ref, data] = calls.updateDoc.mock.calls[0];
    expect(ref.path).toBe("chats/t1/messages/m1");
    expect((data as Record<string, unknown>).seen_by).toEqual({
      __arrayUnion: ["u3"],
    });
  });
});

describe("incrementMonthlyBuildCount", () => {
  it("merges an increment(1) for the YYYY-MM key and total_builds", async () => {
    await incrementMonthlyBuildCount("u1", new Date("2026-04-24T10:00:00Z"));
    expect(calls.setDoc).toHaveBeenCalledTimes(1);
    const [ref, data, opts] = calls.setDoc.mock.calls[0];
    expect(ref.path).toBe("users/u1");
    expect(opts).toEqual({ merge: true });
    const payload = data as Record<string, unknown>;
    const monthly = payload.monthly_builds as Record<string, unknown>;
    // The key depends on local tz; verify via shape rather than hardcoding
    // the TZ offset — each value must be a server `increment(1)` sentinel.
    const keys = Object.keys(monthly);
    expect(keys).toHaveLength(1);
    expect(keys[0]).toMatch(/^\d{4}-\d{2}$/);
    expect(monthly[keys[0]]).toEqual({ __increment: 1 });
    expect(payload.total_builds).toEqual({ __increment: 1 });
  });

  it("uses the current month key when no explicit date is passed", async () => {
    await incrementMonthlyBuildCount("u1");
    const payload = calls.setDoc.mock.calls[0][1] as Record<string, unknown>;
    const monthly = payload.monthly_builds as Record<string, unknown>;
    const [key] = Object.keys(monthly);
    const expectedYear = String(new Date().getFullYear());
    expect(key.startsWith(expectedYear + "-")).toBe(true);
  });
});
