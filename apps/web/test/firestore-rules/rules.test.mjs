// Firestore security-rules tests for apps/web/firestore.rules.
//
// Run with the Firebase emulator:
//   npm install && npm test          (firebase emulators:exec wraps `node --test`)
//
// Covers both that LEGITIMATE access works and that the IDOR / privilege-
// escalation surfaces are denied. Seeding uses withSecurityRulesDisabled so the
// "before" state is set up without going through the rules under test.
import { test, before, after, beforeEach } from "node:test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  initializeTestEnvironment,
  assertSucceeds,
  assertFails,
} from "@firebase/rules-unit-testing";
import {
  doc,
  collection,
  getDoc,
  getDocs,
  setDoc,
  updateDoc,
  deleteDoc,
  addDoc,
} from "firebase/firestore";

const here = dirname(fileURLToPath(import.meta.url));
const ALICE = "alice";
const BOB = "bob";
const CAROL = "carol";

// `firebase emulators:exec` exports FIRESTORE_EMULATOR_HOST (e.g. 127.0.0.1:8088).
// Use it so the suite follows whatever port the emulator actually bound, in CI
// and locally; fall back to the firebase.json default.
function emulatorTarget() {
  const hostPort = process.env.FIRESTORE_EMULATOR_HOST;
  if (hostPort) {
    const idx = hostPort.lastIndexOf(":");
    return { host: hostPort.slice(0, idx), port: Number(hostPort.slice(idx + 1)) };
  }
  return { host: "127.0.0.1", port: 8088 };
}

let env;

before(async () => {
  env = await initializeTestEnvironment({
    projectId: "demo-scheduler",
    firestore: {
      rules: readFileSync(join(here, "..", "..", "firestore.rules"), "utf8"),
      ...emulatorTarget(),
    },
  });
});

after(async () => {
  if (env) await env.cleanup();
});

beforeEach(async () => {
  await env.clearFirestore();
});

// Firestore handle for a signed-in / anonymous user.
const as = (uid) => env.authenticatedContext(uid).firestore();
const anon = () => env.unauthenticatedContext().firestore();
// Seed data bypassing the rules under test.
const seed = (fn) => env.withSecurityRulesDisabled((ctx) => fn(ctx.firestore()));
// Reference to a user doc (matches the rules' selfRef()).
const userRef = (db, uid) => doc(db, "users", uid);

// ----------------------------- auth gate -----------------------------------
test("unauthenticated access is denied", async () => {
  await assertFails(getDoc(doc(anon(), "schedules", "s1")));
});

// ------------------------------- users -------------------------------------
test("user can create their own profile but not another's", async () => {
  await assertSucceeds(setDoc(userRef(as(ALICE), ALICE), { role: "employer" }));
  await assertFails(setDoc(userRef(as(ALICE), BOB), { role: "employee" }));
});

test("role cannot be changed once set", async () => {
  await seed((db) => setDoc(userRef(db, ALICE), { role: "employee" }));
  await assertFails(updateDoc(userRef(as(ALICE), ALICE), { role: "employer" }));
  // A no-role-change update is fine.
  await assertSucceeds(updateDoc(userRef(as(ALICE), ALICE), { display_name: "Al" }));
});

test("client cannot tamper with build counters", async () => {
  await seed((db) => setDoc(userRef(db, ALICE), { role: "employer", total_builds: 5 }));
  await assertFails(updateDoc(userRef(as(ALICE), ALICE), { total_builds: 9999 }));
});

test("profiles are readable by any signed-in user (email lookup)", async () => {
  await seed((db) => setDoc(userRef(db, ALICE), { email: "a@x.com" }));
  await assertSucceeds(getDoc(userRef(as(BOB), ALICE)));
});

// ----------------------------- schedules -----------------------------------
test("schedule create must stamp the caller as created_by", async () => {
  await assertSucceeds(
    setDoc(doc(as(ALICE), "schedules", "s1"), { created_by: ALICE, schedule_name: "Q3" }),
  );
  await assertFails(
    setDoc(doc(as(ALICE), "schedules", "s2"), { created_by: BOB, schedule_name: "forge" }),
  );
});

test("only the owner may update/delete a schedule; created_by is immutable", async () => {
  await seed((db) => setDoc(doc(db, "schedules", "s1"), { created_by: ALICE }));
  await assertSucceeds(updateDoc(doc(as(ALICE), "schedules", "s1"), { schedule_name: "x" }));
  await assertFails(updateDoc(doc(as(BOB), "schedules", "s1"), { schedule_name: "hijack" }));
  await assertFails(deleteDoc(doc(as(BOB), "schedules", "s1")));
  await assertFails(updateDoc(doc(as(ALICE), "schedules", "s1"), { created_by: BOB }));
});

test("built_schedules: owner writes, members read", async () => {
  await seed((db) => setDoc(doc(db, "schedules", "s1"), { created_by: ALICE }));
  await assertSucceeds(
    addDoc(collection(as(ALICE), "schedules", "s1", "built_schedules"), { time_created: 1 }),
  );
  await assertFails(
    addDoc(collection(as(BOB), "schedules", "s1", "built_schedules"), { time_created: 1 }),
  );
  await assertSucceeds(getDocs(collection(as(BOB), "schedules", "s1", "built_schedules")));
});

test("priorities_submissions: a user writes only their own uid slot", async () => {
  await seed((db) => setDoc(doc(db, "schedules", "s1"), { created_by: ALICE }));
  await assertSucceeds(
    setDoc(doc(as(BOB), "schedules", "s1", "priorities_submissions", BOB), { uid: BOB }),
  );
  await assertFails(
    setDoc(doc(as(BOB), "schedules", "s1", "priorities_submissions", ALICE), { uid: ALICE }),
  );
});

// --------------------------- shift_requests --------------------------------
test("shift_requests: requester creates own, non-requester cannot", async () => {
  const path = ["schedules", "s1", "built_schedules", "b1", "shift_requests", "r1"];
  await assertSucceeds(
    setDoc(doc(as(ALICE), ...path), {
      reuqesting_employee: userRef(as(ALICE), ALICE),
      shift_request_status: "PENDING",
    }),
  );
  await assertFails(
    setDoc(doc(as(BOB), ...path.slice(0, -1), "r2"), {
      reuqesting_employee: userRef(as(BOB), ALICE),
      shift_request_status: "PENDING",
    }),
  );
});

// -------------------------- schedule_requests ------------------------------
test("schedule_requests: only the author (from_user) may create", async () => {
  await assertSucceeds(
    addDoc(collection(as(ALICE), "schedule_requests"), {
      from_user: userRef(as(ALICE), ALICE),
      to_user_identification: "b@x.com",
    }),
  );
  await assertFails(
    addDoc(collection(as(BOB), "schedule_requests"), {
      from_user: userRef(as(BOB), ALICE),
      to_user_identification: "c@x.com",
    }),
  );
});

// ----------------------------- notifications -------------------------------
test("notifications: recipient-scoped read + mark-read; no client create", async () => {
  await seed((db) =>
    setDoc(doc(db, "notifications", "n1"), { to_user: userRef(db, ALICE), is_read: false }),
  );
  await assertSucceeds(getDoc(doc(as(ALICE), "notifications", "n1")));
  await assertFails(getDoc(doc(as(BOB), "notifications", "n1")));
  await assertSucceeds(updateDoc(doc(as(ALICE), "notifications", "n1"), { is_read: true }));
  await assertFails(updateDoc(doc(as(BOB), "notifications", "n1"), { is_read: true }));
  await assertFails(
    setDoc(doc(as(ALICE), "notifications", "n2"), { to_user: userRef(as(ALICE), ALICE) }),
  );
});

// -------------------------------- chats ------------------------------------
test("chats: participant gate accepts uid and reference membership", async () => {
  // uid form (web)
  await assertSucceeds(setDoc(doc(as(ALICE), "chats", "c1"), { users: [ALICE, BOB] }));
  await assertFails(setDoc(doc(as(ALICE), "chats", "c2"), { users: [BOB, CAROL] }));
  // reference form (native)
  await assertSucceeds(
    setDoc(doc(as(ALICE), "chats", "c3"), {
      users: [userRef(as(ALICE), ALICE), userRef(as(ALICE), BOB)],
    }),
  );
});

test("chat messages: only a participant may post, sender must be self", async () => {
  await seed((db) => setDoc(doc(db, "chats", "c1"), { users: [ALICE, BOB] }));
  await assertSucceeds(
    setDoc(doc(as(ALICE), "chats", "c1", "messages", "m1"), { sender_uid: ALICE, text: "hi" }),
  );
  await assertFails(
    setDoc(doc(as(CAROL), "chats", "c1", "messages", "m2"), { sender_uid: CAROL, text: "x" }),
  );
  await assertFails(
    setDoc(doc(as(ALICE), "chats", "c1", "messages", "m3"), { sender_uid: BOB, text: "spoof" }),
  );
});

// --------------------- ff_user_push_notifications --------------------------
test("push queue: enqueue allowed, token doc owner-only", async () => {
  await assertSucceeds(
    addDoc(collection(as(ALICE), "ff_user_push_notifications"), { notification_title: "x" }),
  );
  await assertSucceeds(
    setDoc(doc(as(ALICE), "ff_user_push_notifications", ALICE), { fcmToken: "t" }),
  );
  await assertFails(getDoc(doc(as(BOB), "ff_user_push_notifications", ALICE)));
});

// ----------------------------- webhook_events ------------------------------
test("webhook_events: no client access at all", async () => {
  await seed((db) => setDoc(doc(db, "webhook_events", "e1"), { event_type: "x" }));
  await assertFails(getDoc(doc(as(ALICE), "webhook_events", "e1")));
  await assertFails(setDoc(doc(as(ALICE), "webhook_events", "e2"), { event_type: "y" }));
});
