import { describe, it, expect } from "vitest";
import type { Firestore } from "firebase-admin/firestore";
import {
  getChatContactsFor,
  isCallerMemberOfSchedule,
  getScheduleMemberUids,
  getCallerScheduleRefs,
  sharesScheduleWith,
} from "./schedule-contacts";

/**
 * Minimal in-memory Admin-Firestore fake — models documents by path and the
 * exact surface schedule-contacts.ts uses: collection().get() / .doc(),
 * collectionGroup().where('in'|'==').limit().get(), and getAll(). References
 * compare by `.path` (as the real Admin SDK does).
 *
 * It deliberately implements REAL filtering, not scripted returns, so these
 * tests prove the security property — a caller only ever sees co-members of
 * schedules they belong to, never users from another schedule/org.
 */
type Data = Record<string, unknown>;

function makeRef(path: string) {
  const segs = path.split("/");
  return {
    path,
    id: segs[segs.length - 1],
    parent: {
      parent: { id: segs.length >= 3 ? segs[segs.length - 3] : undefined },
    },
  };
}

function snap(path: string, data: Data | undefined) {
  return {
    id: path.split("/").pop() as string,
    ref: makeRef(path),
    exists: data !== undefined,
    data: () => data,
    get: (field: string) => (data ? data[field] : undefined),
  };
}

function refPath(v: unknown): string | undefined {
  return v && typeof v === "object" && "path" in (v as object)
    ? (v as { path: string }).path
    : undefined;
}

function makeDb(docs: Record<string, Data>): Firestore {
  const entries = () => Object.entries(docs);

  function makeQuery(belongs: (path: string) => boolean) {
    const preds: Array<(d: Data) => boolean> = [];
    let lim = Infinity;
    const q = {
      where(field: string, op: "in" | "==", value: unknown) {
        if (op === "in") {
          const set = new Set((value as unknown[]).map(refPath));
          preds.push((d) => set.has(refPath(d[field])));
        } else {
          const target = refPath(value);
          preds.push((d) => refPath(d[field]) === target);
        }
        return q;
      },
      limit(n: number) {
        lim = n;
        return q;
      },
      async get() {
        const out = entries()
          .filter(([p]) => belongs(p))
          .filter(([, d]) => preds.every((fn) => fn(d)))
          .slice(0, lim)
          .map(([p, d]) => snap(p, d));
        return { empty: out.length === 0, docs: out };
      },
    };
    return q;
  }

  const db = {
    collection(path: string) {
      const base = makeQuery(
        (p) =>
          p.startsWith(path + "/") &&
          p.slice(path.length + 1).indexOf("/") === -1
      );
      return Object.assign(base, {
        doc: (id: string) => {
          const p = `${path}/${id}`;
          return Object.assign(makeRef(p), {
            async get() {
              return snap(p, docs[p]);
            },
          });
        },
      });
    },
    collectionGroup(name: string) {
      return makeQuery((p) => {
        const segs = p.split("/");
        return segs.length >= 2 && segs[segs.length - 2] === name;
      });
    },
    async getAll(...refs: Array<{ path: string }>) {
      return refs.map((r) => snap(r.path, docs[r.path]));
    },
  };
  return db as unknown as Firestore;
}

// Fixture: two disjoint schedules (≈ two orgs). Membership is the ENTITLEMENT-
// GATED `schedule_acl` mirror (keyed by schedule id, server-maintained), NOT the
// client-writable `schedules_involved` index.
//   S1 members: alice, bob, carol     S2 members: dave, eve
// alice belongs ONLY to S1 — she must never see dave/eve.
const S1 = makeRef("schedules/S1");
const S2 = makeRef("schedules/S2");

function fixture(): Firestore {
  return makeDb({
    "users/alice": { uid: "alice", display_name: "Alice", email: "alice@a.com" },
    "users/bob": { uid: "bob", display_name: "Bob", email: "bob@a.com" },
    "users/carol": { uid: "carol", display_name: "Carol" }, // no email
    "users/dave": { uid: "dave", display_name: "Dave", email: "dave@b.com" },
    "users/eve": { uid: "eve", display_name: "Eve", email: "eve@b.com" },
    "users/alice/schedule_acl/S1": { schedule_ref: S1 },
    "users/bob/schedule_acl/S1": { schedule_ref: S1 },
    "users/carol/schedule_acl/S1": { schedule_ref: S1 },
    "users/dave/schedule_acl/S2": { schedule_ref: S2 },
    "users/eve/schedule_acl/S2": { schedule_ref: S2 },
    // Mallory SELF-ENROLLED into S1 via the client-writable `schedules_involved`
    // index, but has NO entitlement-gated `schedule_acl` entry. She must be
    // treated as a non-member by every function here.
    "users/mallory": { uid: "mallory", display_name: "Mallory", email: "m@evil.com" },
    "users/mallory/schedules_involved/mi1": { schedules_collection_ref: S1 },
  });
}

describe("schedule-contacts (cross-org enumeration scope, #51 item 8)", () => {
  it("getCallerScheduleRefs returns only the caller's own schedule refs", async () => {
    const refs = await getCallerScheduleRefs(fixture(), "alice");
    expect(refs.map((r) => r.path)).toEqual(["schedules/S1"]);
  });

  it("getChatContactsFor returns ONLY co-members of the caller's schedules", async () => {
    const contacts = await getChatContactsFor(fixture(), "alice");
    const uids = contacts.map((c) => c.uid).sort();
    expect(uids).toEqual(["bob", "carol"]); // NOT dave/eve, NOT alice herself
  });

  it("NEVER leaks users from a schedule the caller is not in (the core fix)", async () => {
    const contacts = await getChatContactsFor(fixture(), "alice");
    const uids = contacts.map((c) => c.uid);
    expect(uids).not.toContain("dave");
    expect(uids).not.toContain("eve");
  });

  it("excludes the caller from their own contact list", async () => {
    const contacts = await getChatContactsFor(fixture(), "alice");
    expect(contacts.map((c) => c.uid)).not.toContain("alice");
  });

  it("maps profiles faithfully and omits a missing email", async () => {
    const contacts = await getChatContactsFor(fixture(), "alice");
    const carol = contacts.find((c) => c.uid === "carol");
    const bob = contacts.find((c) => c.uid === "bob");
    expect(bob?.email).toBe("bob@a.com");
    expect(carol?.display_name).toBe("Carol");
    expect(carol && "email" in carol).toBe(false);
  });

  it("returns [] for a user who belongs to no schedules", async () => {
    expect(await getChatContactsFor(fixture(), "stranger")).toEqual([]);
  });

  it("IGNORES client-writable self-enrollment (schedules_involved without schedule_acl)", async () => {
    // The read-side twin of the IDOR self-enrollment bypass: Mallory wrote a
    // `schedules_involved` doc for S1 but is not entitled (no `schedule_acl`).
    // She must get NO contacts and must NOT count as an S1 member.
    expect(await getChatContactsFor(fixture(), "mallory")).toEqual([]);
    expect(await isCallerMemberOfSchedule(fixture(), "mallory", "S1")).toBe(false);
  });

  it("does NOT surface a self-enrolled non-member in a real member's contacts", async () => {
    const uids = (await getChatContactsFor(fixture(), "alice")).map((c) => c.uid);
    expect(uids).not.toContain("mallory");
  });

  it("isCallerMemberOfSchedule is true for own schedule, false otherwise", async () => {
    expect(await isCallerMemberOfSchedule(fixture(), "alice", "S1")).toBe(true);
    expect(await isCallerMemberOfSchedule(fixture(), "alice", "S2")).toBe(false);
  });

  it("getScheduleMemberUids returns the full roster of ONE schedule (no exclusion)", async () => {
    expect((await getScheduleMemberUids(fixture(), "S1")).sort()).toEqual([
      "alice",
      "bob",
      "carol",
    ]);
    expect((await getScheduleMemberUids(fixture(), "S2")).sort()).toEqual([
      "dave",
      "eve",
    ]);
  });

  it("sharesScheduleWith: self=true, co-member=true, cross-org=false, self-enrolled=false", async () => {
    const db = fixture();
    expect(await sharesScheduleWith(db, "alice", "alice")).toBe(true); // self
    expect(await sharesScheduleWith(db, "alice", "bob")).toBe(true); // S1 co-member
    expect(await sharesScheduleWith(db, "alice", "dave")).toBe(false); // S2 — different org
    expect(await sharesScheduleWith(db, "alice", "mallory")).toBe(false); // self-enrolled non-member
  });

  it(">30 schedules: chunked `in` queries return ALL co-members (no silent truncation)", async () => {
    // Firestore caps `in` operands at 30, so getCoMemberUids batches. A caller
    // with 35 schedules, each with a distinct co-member, must get all 35 back —
    // a refactor to a single >30 `in` query would silently drop the tail.
    const N = 35;
    const docs: Record<string, Record<string, unknown>> = {
      "users/zoe": { uid: "zoe", display_name: "Zoe" },
    };
    for (let i = 0; i < N; i++) {
      const sid = `S${i}`;
      const ref = makeRef(`schedules/${sid}`);
      docs[`users/zoe/schedule_acl/${sid}`] = { schedule_ref: ref };
      docs[`users/peer${i}`] = { uid: `peer${i}`, display_name: `Peer ${i}` };
      docs[`users/peer${i}/schedule_acl/${sid}`] = { schedule_ref: ref };
    }
    const contacts = await getChatContactsFor(makeDb(docs), "zoe");
    const uids = contacts.map((c) => c.uid);
    expect(uids).toHaveLength(N);
    for (let i = 0; i < N; i++) expect(uids).toContain(`peer${i}`);
  });
});
