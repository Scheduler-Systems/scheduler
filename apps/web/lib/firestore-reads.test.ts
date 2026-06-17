import { describe, it, expect, vi, beforeEach } from "vitest";

// Mocked Firestore SDK — each read helper uses doc/getDoc/getDocs. Construct
// tiny fixtures inline per test.

const docMap = new Map<string, { exists: boolean; data: unknown }>();
const collectionMap = new Map<
  string,
  { id: string; data: unknown }[]
>();

function setDoc(path: string, data: unknown) {
  docMap.set(path, { exists: true, data });
}
function missingDoc(path: string) {
  docMap.set(path, { exists: false, data: null });
}
function setCollection(path: string, docs: { id: string; data: unknown }[]) {
  collectionMap.set(path, docs);
}

vi.mock("firebase/firestore", () => ({
  collection: (_db: unknown, ...segments: string[]) => ({
    type: "collection",
    path: segments.join("/"),
  }),
  doc: (_db: unknown, ...segments: string[]) => ({
    type: "doc",
    path: segments.join("/"),
    id: segments[segments.length - 1],
  }),
  getDoc: async (ref: { path: string; id: string }) => {
    const entry = docMap.get(ref.path) ?? { exists: false, data: null };
    return {
      exists: () => entry.exists,
      data: () => entry.data,
      id: ref.id,
    };
  },
  getDocs: async (refOrQuery: { path?: string }) => {
    const path = refOrQuery.path ?? "";
    const docs = collectionMap.get(path) ?? [];
    return {
      empty: docs.length === 0,
      docs: docs.map((d) => ({
        id: d.id,
        data: () => d.data,
        ref: { type: "doc", path: `${path}/${d.id}`, id: d.id },
      })),
    };
  },
  query: (ref: { path: string }) => ({ path: ref.path }),
  orderBy: () => undefined,
  limit: () => undefined,
}));

vi.mock("./firebase", () => ({
  getFirebaseDb: () => ({ __mock_db: true }),
}));

const {
  getSchedule,
  getUserSchedules,
  getUserProfile,
  getPrioritySubmission,
  getAllPrioritySubmissions,
  getLatestBuiltSchedule,
  getBuiltSchedules,
  getDashboardSummary,
  getMonthlyBuildCount,
  buildCountMonthKey,
  isEmployerRole,
} = await import("./firestore");

beforeEach(() => {
  docMap.clear();
  collectionMap.clear();
});

describe("getSchedule", () => {
  it("returns the schedule with id spread when the doc exists", async () => {
    setDoc("schedules/s1", { schedule_name: "Test", employees: [] });
    const out = await getSchedule("s1");
    expect(out?.id).toBe("s1");
    expect(out?.schedule_name).toBe("Test");
  });

  it("returns null when the schedule is missing", async () => {
    missingDoc("schedules/s2");
    expect(await getSchedule("s2")).toBeNull();
  });
});

describe("getBuiltSchedules", () => {
  it("returns an empty list when the subcollection is empty", async () => {
    setCollection("schedules/sid1/built_schedules", []);
    const out = await getBuiltSchedules("sid1");
    expect(out).toEqual([]);
  });

  it("returns all docs in the subcollection ordered by time_created desc", async () => {
    setCollection("schedules/sid1/built_schedules", [
      { id: "b1", data: { first_weekday: "2026-05-03", time_created: 3 } },
      { id: "b2", data: { first_weekday: "2026-05-10", time_created: 1 } },
      { id: "b3", data: { first_weekday: "2026-05-17", time_created: 2 } },
    ]);
    const out = await getBuiltSchedules("sid1");
    expect(out).toHaveLength(3);
    // Order mirrors the collection (query-ordering is a server-side concern).
    expect(out[0].id).toBe("b1");
    expect(out[1].id).toBe("b2");
    expect(out[2].id).toBe("b3");
  });
});

describe("getUserProfile", () => {
  it("returns the user doc including the canonical role string", async () => {
    setDoc("users/u1", { email: "u@x", display_name: "U", role: "employer" });
    const p = await getUserProfile("u1");
    expect(p?.role).toBe("employer");
    expect(isEmployerRole(p?.role)).toBe(true);
  });

  it("returns null when the user doc does not exist", async () => {
    missingDoc("users/u-missing");
    expect(await getUserProfile("u-missing")).toBeNull();
  });

  it("tolerates legacy RoleStruct on read", async () => {
    setDoc("users/u2", {
      email: "u@x",
      display_name: "U",
      role: { is_admin: true, is_worker: true },
    });
    const p = await getUserProfile("u2");
    expect(isEmployerRole(p?.role)).toBe(true);
  });

  it("returns true when only is_creator is true (is_admin is false)", async () => {
    setDoc("users/u3", {
      email: "u@x",
      display_name: "U",
      role: { is_creator: true, is_admin: false },
    });
    const p = await getUserProfile("u3");
    expect(isEmployerRole(p?.role)).toBe(true);
  });

  it("returns false when role is undefined", async () => {
    expect(isEmployerRole(undefined)).toBe(false);
    setDoc("users/u4", { email: "u@x", display_name: "U" }); // no role field
    const p = await getUserProfile("u4");
    expect(isEmployerRole(p?.role)).toBe(false);
  });
});

describe("getUserSchedules", () => {
  it("follows schedules_involved references to the actual schedule docs", async () => {
    setCollection("users/u1/schedules_involved", [
      {
        id: "sched1",
        data: {
          schedules_collection_ref: { type: "doc", path: "schedules/sched1" },
        },
      },
    ]);
    setDoc("schedules/sched1", { schedule_name: "S1", employees: [] });
    const out = await getUserSchedules("u1");
    expect(out).toHaveLength(1);
    expect(out[0].schedule_name).toBe("S1");
  });

  it("filters out schedules whose doc was deleted (null from snapshot)", async () => {
    setCollection("users/u1/schedules_involved", [
      {
        id: "orphan",
        data: {
          schedules_collection_ref: { type: "doc", path: "schedules/orphan" },
        },
      },
    ]);
    missingDoc("schedules/orphan");
    const out = await getUserSchedules("u1");
    expect(out).toHaveLength(0);
  });
});

describe("getPrioritySubmission", () => {
  it("returns Flutter bools translated to cell keys when priorities_private has any true", async () => {
    const bools = new Array(21).fill(false);
    bools[0] = true;
    bools[5] = true;
    setDoc("users/u1/schedules_involved/sid1", { priorities_private: bools });
    missingDoc("schedules/sid1/priorities_submissions/u1");
    const sub = await getPrioritySubmission("sid1", "u1");
    expect(sub?.priorities).toEqual(["Sun|morning", "Mon|night"]);
  });

  it("falls back to the Next.js subcollection doc when Flutter bools all-false", async () => {
    setDoc("users/u1/schedules_involved/sid1", {
      priorities_private: new Array(21).fill(false),
    });
    setDoc("schedules/sid1/priorities_submissions/u1", {
      display_name: "Legacy",
      priorities: ["Sun|morning"],
      submitted_at: null,
    });
    const sub = await getPrioritySubmission("sid1", "u1");
    expect(sub?.display_name).toBe("Legacy");
    expect(sub?.priorities).toEqual(["Sun|morning"]);
  });

  it("returns null when neither location has data", async () => {
    missingDoc("users/u1/schedules_involved/sid1");
    missingDoc("schedules/sid1/priorities_submissions/u1");
    expect(await getPrioritySubmission("sid1", "u1")).toBeNull();
  });

  it("falls back to sub collection when involved doc exists but priorities_private is missing", async () => {
    setDoc("users/u1/schedules_involved/sid1", {});
    setDoc("schedules/sid1/priorities_submissions/u1", {
      display_name: "NoFlutter",
      priorities: ["Tue|morning"],
      submitted_at: null,
    });
    const sub = await getPrioritySubmission("sid1", "u1");
    expect(sub?.display_name).toBe("NoFlutter");
    expect(sub?.priorities).toEqual(["Tue|morning"]);
  });
});

describe("getAllPrioritySubmissions", () => {
  it("merges Flutter + Next.js sources; Flutter bools win on conflict", async () => {
    // Seed employees with user_ref.id = 'u1'
    setDoc("schedules/sid1", {
      schedule_name: "S",
      employees: [
        {
          employee_name: "Uno",
          user_ref: { id: "u1", path: "users/u1" },
        },
      ],
    });
    setCollection("schedules/sid1/priorities_submissions", [
      {
        id: "u1",
        data: {
          uid: "u1",
          display_name: "Legacy",
          priorities: ["Sun|morning"],
          submitted_at: null,
        },
      },
    ]);
    const bools = new Array(21).fill(false);
    bools[5] = true; // Mon|night
    setDoc("users/u1/schedules_involved/sid1", { priorities_private: bools });

    const all = await getAllPrioritySubmissions("sid1");
    expect(all).toHaveLength(1);
    // Flutter location wins → Mon|night not Sun|morning
    expect(all[0].priorities).toEqual(["Mon|night"]);
    expect(all[0].display_name).toBe("Legacy"); // display_name preserved from the Next.js doc
  });

  it("returns only Next.js-side submissions when no Flutter data", async () => {
    setDoc("schedules/sid1", { schedule_name: "S", employees: [] });
    setCollection("schedules/sid1/priorities_submissions", [
      {
        id: "u1",
        data: {
          uid: "u1",
          display_name: "U",
          priorities: ["Sun|morning"],
          submitted_at: null,
        },
      },
    ]);
    missingDoc("users/u1/schedules_involved/sid1");

    const all = await getAllPrioritySubmissions("sid1");
    expect(all).toHaveLength(1);
    expect(all[0].priorities).toEqual(["Sun|morning"]);
  });

  it("collects submissions when the schedule doc does not exist (null schedule)", async () => {
    missingDoc("schedules/sid1");
    setCollection("schedules/sid1/priorities_submissions", [
      {
        id: "u1",
        data: {
          uid: "u1",
          display_name: "Orphan",
          priorities: ["Fri|night"],
          submitted_at: null,
        },
      },
    ]);
    const all = await getAllPrioritySubmissions("sid1");
    expect(all).toHaveLength(1);
    expect(all[0].priorities).toEqual(["Fri|night"]);
  });

  it("skips employee with null user_ref.id (no uid)", async () => {
    setDoc("schedules/sid1", {
      schedule_name: "S",
      employees: [
        { employee_name: "NoUid", user_ref: null },
        { employee_name: "MissingId", user_ref: {} },
      ],
    });
    setCollection("schedules/sid1/priorities_submissions", [
      { id: "u1", data: { uid: "u1", display_name: "U", priorities: ["Sat|morning"], submitted_at: null } },
    ]);
    missingDoc("users/u1/schedules_involved/sid1");
    const all = await getAllPrioritySubmissions("sid1");
    expect(all).toHaveLength(1);
  });

  it("skips involved doc with all-false priorities_private (no override)", async () => {
    setDoc("schedules/sid1", {
      schedule_name: "S",
      employees: [
        { employee_name: "U", user_ref: { id: "u1", path: "users/u1" } },
      ],
    });
    setCollection("schedules/sid1/priorities_submissions", [
      { id: "u1", data: { uid: "u1", display_name: "U", priorities: ["Sun|morning"], submitted_at: null } },
    ]);
    // priorities_private all false — should be skipped
    const boolsAllFalse = new Array(21).fill(false);
    setDoc("users/u1/schedules_involved/sid1", { priorities_private: boolsAllFalse });
    const all = await getAllPrioritySubmissions("sid1");
    expect(all).toHaveLength(1);
    // Next.js data is preserved because all-false bools are skipped
    expect(all[0].priorities).toEqual(["Sun|morning"]);
  });

  it("Flutter override for a uid with no priorities_submission uses empty display_name", async () => {
    setDoc("schedules/sid1", { schedule_name: "S", employees: [{ user_ref: { id: "u2" } }] });
    setCollection("schedules/sid1/priorities_submissions", [{ id: "u1", data: { priorities: ["Sun|morning"], submitted_at: null } }]);
    const bools = new Array(21).fill(false);
    bools[0] = true;
    setDoc("users/u2/schedules_involved/sid1", { priorities_private: bools });
    const all = await getAllPrioritySubmissions("sid1");
    expect(all).toHaveLength(2);
    const override = all.find((s) => s.uid === "u2");
    expect(override).toBeDefined();
    expect(override?.display_name).toBe("");
    expect(override?.priorities).toEqual(["Sun|morning"]);
  });
});

describe("getLatestBuiltSchedule", () => {
  it("returns null on an empty subcollection", async () => {
    setCollection("schedules/sid1/built_schedules", []);
    expect(await getLatestBuiltSchedule("sid1")).toBeNull();
  });

  it("returns the first doc when non-empty", async () => {
    setCollection("schedules/sid1/built_schedules", [
      { id: "b1", data: { first_weekday: "2026-05-03" } },
    ]);
    const b = await getLatestBuiltSchedule("sid1");
    expect(b?.id).toBe("b1");
    expect(b?.first_weekday).toBe("2026-05-03");
  });
});

describe("getMonthlyBuildCount", () => {
  it("returns 0 when the user doc doesn't exist", async () => {
    missingDoc("users/u1");
    expect(await getMonthlyBuildCount("u1")).toBe(0);
  });

  it("returns 0 when monthly_builds map is missing", async () => {
    setDoc("users/u1", {});
    expect(await getMonthlyBuildCount("u1")).toBe(0);
  });

  it("returns 0 when the current-month key is absent from the map", async () => {
    const now = new Date("2026-04-24T10:00:00Z");
    setDoc("users/u1", { monthly_builds: { "2025-12": 3 } });
    expect(await getMonthlyBuildCount("u1", now)).toBe(0);
  });

  it("returns the stored count for the current month", async () => {
    const now = new Date("2026-04-24T10:00:00Z");
    const key = buildCountMonthKey(now);
    setDoc("users/u1", { monthly_builds: { [key]: 4 } });
    expect(await getMonthlyBuildCount("u1", now)).toBe(4);
  });

  it("rejects non-number / negative / NaN stored values, falling back to 0", async () => {
    const now = new Date("2026-04-24T10:00:00Z");
    const key = buildCountMonthKey(now);
    setDoc("users/u1", { monthly_builds: { [key]: "five" } });
    expect(await getMonthlyBuildCount("u1", now)).toBe(0);

    setDoc("users/u1", { monthly_builds: { [key]: -1 } });
    expect(await getMonthlyBuildCount("u1", now)).toBe(0);
  });
});

describe("getDashboardSummary", () => {
  it("counts schedules + unique employee emails across all schedules", async () => {
    setCollection("users/u1/schedules_involved", [
      {
        id: "s1",
        data: {
          schedules_collection_ref: { type: "doc", path: "schedules/s1" },
        },
      },
      {
        id: "s2",
        data: {
          schedules_collection_ref: { type: "doc", path: "schedules/s2" },
        },
      },
    ]);
    setDoc("schedules/s1", {
      schedule_name: "A",
      employees: [{ employee_email: "x@x" }, { employee_email: "y@y" }],
    });
    setDoc("schedules/s2", {
      schedule_name: "B",
      employees: [{ employee_email: "x@x" }, { employee_email: "z@z" }],
    });
    const out = await getDashboardSummary("u1");
    expect(out.scheduleCount).toBe(2);
    expect(out.employeeCount).toBe(3); // x, y, z (dedup on x)
    expect(out.schedules).toHaveLength(2);
  });

  it("handles schedules with null employees gracefully", async () => {
    setCollection("users/u1/schedules_involved", [
      {
        id: "s1",
        data: {
          schedules_collection_ref: { type: "doc", path: "schedules/s1" },
        },
      },
    ]);
    setDoc("schedules/s1", {
      schedule_name: "NullEmp",
      employees: null,
    });
    const out = await getDashboardSummary("u1");
    expect(out.scheduleCount).toBe(1);
    expect(out.employeeCount).toBe(0);
    expect(out.schedules[0].employeeCount).toBe(0);
  });

  it("counts only employees with non-empty emails", async () => {
    setCollection("users/u1/schedules_involved", [
      {
        id: "s1",
        data: {
          schedules_collection_ref: { type: "doc", path: "schedules/s1" },
        },
      },
    ]);
    setDoc("schedules/s1", {
      schedule_name: "Partial",
      employees: [
        { employee_email: "" },
        { employee_email: "a@b" },
      ],
    });
    const out = await getDashboardSummary("u1");
    expect(out.employeeCount).toBe(1);
  });
});
