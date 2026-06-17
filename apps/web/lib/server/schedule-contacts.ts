import type {
  DocumentReference,
  Firestore,
} from "firebase-admin/firestore";

/**
 * Server-side schedule-membership resolution — the authorization core behind
 * the chat-contacts picker and the employees listing.
 *
 * SECURITY (#51 item 8 — cross-org user enumeration). The web app must never
 * expose the global user directory. The only people a caller may see are those
 * they actually share a schedule with. This module derives that set from the
 * caller's *verified* uid using the Admin SDK, so the scope cannot be widened
 * by a client-supplied parameter.
 *
 * Source of truth = `users/{uid}/schedule_acl/{scheduleId}` — the
 * ENTITLEMENT-GATED, server-maintained membership mirror (written only by the
 * firestore-idor-acl-maintainer Cloud Function + the one-time backfill; clients
 * cannot write it — `allow write: if false`). Each doc is keyed by schedule id
 * and carries a `schedule_ref` field pointing at `schedules/{id}`.
 *
 * We deliberately do NOT read `users/{uid}/schedules_involved` here: that index
 * IS client-writable (`allow create: if isOwner(...)`), so a user could
 * self-enroll into a schedule they don't belong to and then enumerate its
 * members — the read-side twin of the IDOR self-enrollment bypass
 * (docs/firestore-idor-fix/FINDING-self-enrollment-bypass.md). `schedule_acl`
 * only ever contains entitled memberships, so reading it is safe. This couples
 * contact resolution to the IDOR backfill, which is correct: the chat surface
 * goes public only behind the same security rollout that runs that backfill and
 * deploys the tightened rules.
 */

const USERS_COLLECTION = "users";
const ACL_SUBCOLLECTION = "schedule_acl";
const SCHEDULE_REF_FIELD = "schedule_ref";

/** Firestore caps `in` / `array-contains-any` operands at 30 per query. */
export const IN_QUERY_LIMIT = 30;

export interface ContactUser {
  /** `uid` field on the user doc — the value a chat thread stores in `users[]`. */
  uid: string;
  /** Display name; empty string when the profile hasn't set one. */
  display_name: string;
  /** Optional email, used as a secondary label when display_name is blank. */
  email?: string;
}

function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    out.push(items.slice(i, i + size));
  }
  return out;
}

/** De-duplicate DocumentReferences by their stored path. */
function dedupeRefs(refs: DocumentReference[]): DocumentReference[] {
  const seen = new Map<string, DocumentReference>();
  for (const ref of refs) {
    if (!seen.has(ref.path)) seen.set(ref.path, ref);
  }
  return [...seen.values()];
}

/**
 * The schedule DocumentReferences the caller is an ENTITLED member of, read
 * from their own `schedule_acl` subcollection. Empty when the caller belongs to
 * no schedules — callers render an empty picker.
 */
export async function getCallerScheduleRefs(
  db: Firestore,
  callerUid: string
): Promise<DocumentReference[]> {
  const snap = await db
    .collection(`${USERS_COLLECTION}/${callerUid}/${ACL_SUBCOLLECTION}`)
    .get();
  const refs = snap.docs
    .map((d) => d.get(SCHEDULE_REF_FIELD) as DocumentReference | undefined)
    .filter((r): r is DocumentReference => Boolean(r));
  return dedupeRefs(refs);
}

/**
 * Every user uid that is an entitled member of ANY of `scheduleRefs`, via a
 * collection-group reverse lookup on `schedule_acl`. `excludeUid` (when given)
 * is dropped. Requires a collection-group index on `schedule_acl.schedule_ref`
 * in production (added to firestore.indexes.json in scheduler-api); the emulator
 * needs none.
 */
export async function getCoMemberUids(
  db: Firestore,
  scheduleRefs: DocumentReference[],
  excludeUid?: string
): Promise<string[]> {
  if (scheduleRefs.length === 0) return [];
  const uids = new Set<string>();
  for (const batch of chunk(scheduleRefs, IN_QUERY_LIMIT)) {
    const snap = await db
      .collectionGroup(ACL_SUBCOLLECTION)
      .where(SCHEDULE_REF_FIELD, "in", batch)
      .get();
    for (const doc of snap.docs) {
      // doc path: users/{uid}/schedule_acl/{scheduleId} → grandparent = uid.
      const uid = doc.ref.parent.parent?.id;
      if (uid && uid !== excludeUid) uids.add(uid);
    }
  }
  return [...uids];
}

/**
 * All member uids of a SINGLE schedule (no caller exclusion) — the roster
 * behind the scoped employees listing. The caller must be authorized to see
 * this (see {@link isCallerMemberOfSchedule}) before it is called.
 */
export async function getScheduleMemberUids(
  db: Firestore,
  scheduleId: string
): Promise<string[]> {
  const scheduleRef = db.collection("schedules").doc(scheduleId);
  return getCoMemberUids(db, [scheduleRef]);
}

/**
 * Is the caller an ENTITLED member of `scheduleId`? A single by-id read of the
 * server-maintained ACL doc (`users/{uid}/schedule_acl/{scheduleId}`) — the same
 * signal the Firestore rules use (`hasScheduleAcl`). Used to authorize a scoped
 * employees query so a caller may only list the roster of a schedule they
 * actually belong to (closes the IDOR of passing an arbitrary scheduleId).
 */
export async function isCallerMemberOfSchedule(
  db: Firestore,
  callerUid: string,
  scheduleId: string
): Promise<boolean> {
  const snap = await db
    .collection(`${USERS_COLLECTION}/${callerUid}/${ACL_SUBCOLLECTION}`)
    .doc(scheduleId)
    .get();
  return snap.exists;
}

/**
 * Does the caller share at least one schedule with `targetUid` (or is the
 * target the caller themselves)? Authorizes a by-id user read/mutation so a
 * caller can only touch profiles within their own schedules — closing the
 * /api/employees/[id] IDOR where any authed user could read/rename/delete any
 * user by uid.
 */
export async function sharesScheduleWith(
  db: Firestore,
  callerUid: string,
  targetUid: string
): Promise<boolean> {
  if (callerUid === targetUid) return true;
  const refs = await getCallerScheduleRefs(db, callerUid);
  if (refs.length === 0) return false;
  const coMembers = await getCoMemberUids(db, refs, callerUid);
  return coMembers.includes(targetUid);
}

/**
 * Resolve a set of uids to minimal contact profiles via get-by-id reads (the
 * only `users` access still allowed to clients; the Admin SDK bypasses rules
 * regardless). Missing docs and the caller are filtered out.
 */
export async function resolveUserProfiles(
  db: Firestore,
  uids: string[],
  excludeUid?: string
): Promise<ContactUser[]> {
  const targets = uids.filter((u) => u !== excludeUid);
  if (targets.length === 0) return [];
  const refs = targets.map((uid) => db.collection(USERS_COLLECTION).doc(uid));
  const docs = await db.getAll(...refs);
  return docs
    .filter((d) => d.exists)
    .map((d) => {
      const data = d.data() as {
        uid?: string;
        display_name?: string;
        email?: string;
      };
      const contact: ContactUser = {
        uid: data.uid ?? d.id,
        display_name: data.display_name ?? "",
      };
      if (data.email) contact.email = data.email;
      return contact;
    })
    .filter((c) => c.uid !== excludeUid);
}

/**
 * The caller's full chat-contact set: every entitled co-member of every schedule
 * they belong to, resolved to profiles. This is the one function the contacts
 * endpoint needs.
 */
export async function getChatContactsFor(
  db: Firestore,
  callerUid: string
): Promise<ContactUser[]> {
  const scheduleRefs = await getCallerScheduleRefs(db, callerUid);
  if (scheduleRefs.length === 0) return [];
  const coMemberUids = await getCoMemberUids(db, scheduleRefs, callerUid);
  return resolveUserProfiles(db, coMemberUids, callerUid);
}
