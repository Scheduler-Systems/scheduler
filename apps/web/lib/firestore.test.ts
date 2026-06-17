import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ---------------------------------------------------------------------------
// REST API fallback tests for lib/firestore.ts
//
// The existing firestore-reads.test.ts covers direct-Firestore paths.  This
// file covers the REST API branches (`apiEnabled() === true`) and the
// apiScheduleToLegacy mapping that firestore-reads.test.ts doesn't reach.
// ---------------------------------------------------------------------------

const mockListSchedules = vi.fn();
const mockGetSchedule = vi.fn();

vi.mock("@/lib/api/client", () => ({
  listSchedules: (...args: unknown[]) => mockListSchedules(...args),
  getSchedule: (...args: unknown[]) => mockGetSchedule(...args),
}));

// Firestore SDK mock — needed because the fallback path calls getDoc/getDocs.
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

vi.mock("@/lib/firebase", () => ({
  getFirebaseDb: () => ({ __mock_db: true }),
}));

// Build API schedule fixtures.
function makeApiSchedule(overrides: Partial<{
  id: string;
  name: string;
  settings: Record<string, unknown>;
}> = {}) {
  return {
    id: overrides.id ?? "s-api-1",
    tenantId: "test-tenant",
    name: overrides.name ?? "API Schedule",
    settings: overrides.settings ?? {},
    status: "active",
    createdBy: "u1",
    createdAt: "2026-05-01T00:00:00Z",
    updatedAt: "2026-05-01T00:00:00Z",
  };
}

describe("lib/firestore — REST API fallback", () => {
  let originalApiUrl: string | undefined;
  let originalProjectId: string | undefined;

  beforeEach(() => {
    originalApiUrl = process.env.NEXT_PUBLIC_SCHEDULER_API_URL;
    originalProjectId = process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID;
    process.env.NEXT_PUBLIC_SCHEDULER_API_URL = "http://api.test";
    process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID = "test-project";
    docMap.clear();
    collectionMap.clear();
    mockListSchedules.mockReset();
    mockGetSchedule.mockReset();
  });

  afterEach(() => {
    if (originalApiUrl === undefined) {
      delete process.env.NEXT_PUBLIC_SCHEDULER_API_URL;
    } else {
      process.env.NEXT_PUBLIC_SCHEDULER_API_URL = originalApiUrl;
    }
    if (originalProjectId === undefined) {
      delete process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID;
    } else {
      process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID = originalProjectId;
    }
  });

  describe("apiScheduleToLegacy mapping (tested through getSchedule)", () => {
    it("maps a bare API schedule to the legacy shape with defaults", async () => {
      mockGetSchedule.mockResolvedValueOnce(makeApiSchedule());
      const { getSchedule } = await import("./firestore");
      const result = await getSchedule("s-api-1");
      expect(result).not.toBeNull();
      expect(result?.id).toBe("s-api-1");
      expect(result?.schedule_name).toBe("API Schedule");
      expect(result?.employees).toEqual([]);
      expect(result?.current_priorities).toEqual([]);
      expect(result?.schedule_settings).toBeNull();
      expect(result?.sid).toBe("");
      expect(result?.next_schedule).toEqual([]);
    });

    it("extracts employees, current_priorities, and schedule_settings from settings", async () => {
      mockGetSchedule.mockResolvedValueOnce(
        makeApiSchedule({
          settings: {
            employees: [
              {
                employee_name: "Ada",
                employee_email: "ada@x",
                role: { is_worker: true },
              },
            ],
            current_priorities: ["Sun|morning"],
            schedule_settings: {
              num_of_stations: 2,
              enabled_shifts: ["morning", "night"],
            },
          },
        }),
      );
      const { getSchedule } = await import("./firestore");
      const result = await getSchedule("s-api-2");
      expect(result?.employees).toHaveLength(1);
      expect(result?.employees[0].employee_name).toBe("Ada");
      expect(result?.current_priorities).toEqual(["Sun|morning"]);
      expect(result?.schedule_settings?.num_of_stations).toBe(2);
    });

    it("handles a bare API response with no settings key at all", async () => {
      mockGetSchedule.mockResolvedValueOnce({
        id: "s-bare",
        name: "Bare",
        tenantId: "t1",
        status: "active",
        createdBy: "u1",
        createdAt: "2026-01-01T00:00:00Z",
        updatedAt: "2026-01-01T00:00:00Z",
      });
      const { getSchedule } = await import("./firestore");
      const result = await getSchedule("s-bare");
      expect(result).not.toBeNull();
      expect(result?.id).toBe("s-bare");
      expect(result?.employees).toEqual([]);
      expect(result?.current_priorities).toEqual([]);
      expect(result?.schedule_settings).toBeNull();
    });

    it("handles null settings gracefully", async () => {
      mockGetSchedule.mockResolvedValueOnce(
        makeApiSchedule({ settings: undefined as unknown as Record<string, unknown> }),
      );
      const { getSchedule } = await import("./firestore");
      const result = await getSchedule("s-api-null-settings");
      expect(result?.employees).toEqual([]);
      expect(result?.current_priorities).toEqual([]);
      expect(result?.schedule_settings).toBeNull();
    });
  });

  describe("getSchedule — REST API path", () => {
    it("calls the API and returns the mapped schedule on success", async () => {
      mockGetSchedule.mockResolvedValueOnce(makeApiSchedule({ id: "s1", name: "From API" }));
      const { getSchedule } = await import("./firestore");
      const result = await getSchedule("s1");
      expect(mockGetSchedule).toHaveBeenCalledWith("s1");
      expect(result?.schedule_name).toBe("From API");
    });

    it("falls back to Firestore when the API call throws", async () => {
      mockGetSchedule.mockRejectedValueOnce(new Error("network error"));
      setDoc("schedules/s1", { schedule_name: "FS Fallback", employees: [] });
      const { getSchedule } = await import("./firestore");
      const result = await getSchedule("s1");
      expect(result?.schedule_name).toBe("FS Fallback");
    });

    it("returns null when both API and Firestore fail", async () => {
      mockGetSchedule.mockRejectedValueOnce(new Error("network error"));
      missingDoc("schedules/missing");
      const { getSchedule } = await import("./firestore");
      const result = await getSchedule("missing");
      expect(result).toBeNull();
    });
  });

  describe("getUserSchedules — REST API path", () => {
    it("calls listSchedules and maps each item", async () => {
      mockListSchedules.mockResolvedValueOnce({
        items: [
          makeApiSchedule({ id: "s1", name: "Sched 1" }),
          makeApiSchedule({ id: "s2", name: "Sched 2" }),
        ],
      });
      const { getUserSchedules } = await import("./firestore");
      const results = await getUserSchedules("u1");
      expect(mockListSchedules).toHaveBeenCalled();
      expect(results).toHaveLength(2);
      expect(results[0].schedule_name).toBe("Sched 1");
      expect(results[1].schedule_name).toBe("Sched 2");
    });

    it("falls back to Firestore schedules_involved when the API fails", async () => {
      mockListSchedules.mockRejectedValueOnce(new Error("API unavailable"));
      setCollection("users/u1/schedules_involved", [
        {
          id: "fs1",
          data: {
            schedules_collection_ref: { type: "doc", path: "schedules/fs1" },
          },
        },
      ]);
      setDoc("schedules/fs1", { schedule_name: "FS Result", employees: [] });
      const { getUserSchedules } = await import("./firestore");
      const results = await getUserSchedules("u1");
      expect(results).toHaveLength(1);
      expect(results[0].schedule_name).toBe("FS Result");
    });
  });
});
