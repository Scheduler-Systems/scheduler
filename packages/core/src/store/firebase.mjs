import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

let firestore = null;
let fbInitialized = false;

function resolveFirebase() {
  if (fbInitialized) return firestore;
  fbInitialized = true;

  let admin;
  try {
    admin = require("firebase-admin");
  } catch {
    throw new Error(
      "firebase-admin must be installed. Run: npm install firebase-admin",
    );
  }

  const emulatorHost = process.env.FIRESTORE_EMULATOR_HOST;
  const projectId =
    process.env.GCLOUD_PROJECT ||
    process.env.FIREBASE_PROJECT_ID ||
    "your-firebase-project-id"; // SCRUBBED: set GCLOUD_PROJECT / FIREBASE_PROJECT_ID

  let apps;
  try {
    apps = admin.apps || [];
  } catch {
    apps = [];
  }

  if (apps.length === 0) {
    const opts = { projectId };

    const credJson = process.env.FIREBASE_SERVICE_ACCOUNT;
    const credPath = process.env.GOOGLE_APPLICATION_CREDENTIALS;

    if (credJson) {
      let parsed;
      try {
        parsed = JSON.parse(credJson);
      } catch {
        parsed = credJson;
      }
      opts.credential = admin.credential.cert(parsed);
    } else if (credPath) {
      opts.credential = admin.credential.cert(credPath);
    }

    admin.initializeApp(opts);
  }

  firestore = admin.firestore();

  if (emulatorHost) {
    const [host, port] = emulatorHost.split(":");
    firestore.settings({
      host: `${host}:${port || 8080}`,
      ssl: false,
    });
  }

  return firestore;
}

export function isFirebaseAvailable() {
  try {
    require("firebase-admin");
    return true;
  } catch {
    return false;
  }
}

export function createFirebaseStore() {
  const db = resolveFirebase();

  return {
    async listSchedules(tenantId) {
      const snapshot = await safeOrderedQuery(
        db.collection("schedules"),
        "tenantId",
        tenantId,
        "createdAt",
        "desc",
      );
      const items = [];
      snapshot.forEach((doc) => {
        items.push({ id: doc.id, ...doc.data() });
      });
      return items;
    },

    async putSchedule(schedule) {
      const docRef = db.collection("schedules").doc(schedule.id);
      const doc = await docRef.get();
      const now = new Date().toISOString();

      let data;
      if (doc.exists) {
        const existing = doc.data();
        data = { ...existing, ...schedule, updatedAt: now };
      } else {
        data = {
          ...schedule,
          createdAt: schedule.createdAt || now,
          updatedAt: now,
        };
      }

      await docRef.set(data, { merge: true });
      return { id: schedule.id, ...data };
    },

    async getSchedule(tenantId, scheduleId) {
      const doc = await db.collection("schedules").doc(scheduleId).get();
      if (!doc.exists) return null;
      const data = doc.data();
      return data.tenantId !== tenantId ? null : { id: doc.id, ...data };
    },

    async deleteSchedule(tenantId, scheduleId) {
      await db.collection("schedules").doc(scheduleId).delete();
    },

    async putAvailability(entry) {
      await db
        .collection("availability")
        .doc(entry.id)
        .set(entry, { merge: true });
      return entry;
    },

    async getAvailability(id) {
      const doc = await db.collection("availability").doc(id).get();
      return doc.exists ? doc.data() : null;
    },

    async putDraft(draft) {
      await db.collection("drafts").doc(draft.id).set(draft, { merge: true });
      return draft;
    },

    async getDraft(id) {
      const doc = await db.collection("drafts").doc(id).get();
      return doc.exists ? doc.data() : null;
    },

    async deleteDraft(id) {
      await db.collection("drafts").doc(id).delete();
    },

    async putRequest(req) {
      await db
        .collection("schedule_requests")
        .doc(req.id)
        .set(req, { merge: true });
      return req;
    },

    async getRequest(id) {
      const doc = await db.collection("schedule_requests").doc(id).get();
      return doc.exists ? doc.data() : null;
    },

    async putImport(result) {
      await db
        .collection("imports")
        .doc(result.importId)
        .set(result, { merge: true });
      return result;
    },

    async getImport(importId) {
      const doc = await db.collection("imports").doc(importId).get();
      return doc.exists ? doc.data() : null;
    },

    async listImports(tenantId, limit = 50) {
      const snapshot = await safeOrderedQuery(
        db.collection("imports"),
        "tenantId",
        tenantId,
        "createdAt",
        "desc",
        Math.min(limit, 100),
      );
      return snapshot.docs.map((doc) => doc.data());
    },

    async putApproval(approval) {
      await db
        .collection("approvals")
        .doc(approval.id)
        .set(approval, { merge: true });
      return approval;
    },

    async listEmployees(tenantId) {
      const snapshot = await db.collection("employees").where("tenantId", "==", tenantId).get();
      return snapshot.docs.map((doc) => ({ id: doc.id, ...doc.data() }));
    },

    async putEmployee(employee) {
      const ref = db.collection("employees").doc(employee.id);
      await ref.set({ ...employee, updatedAt: new Date().toISOString() }, { merge: true });
      return employee;
    },

    async getEmployee(tenantId, employeeId) {
      const doc = await db.collection("employees").doc(employeeId).get();
      if (!doc.exists) return null;
      const data = doc.data();
      return data.tenantId !== tenantId ? null : { id: doc.id, ...data };
    },

    async deleteEmployee(tenantId, employeeId) {
      await db.collection("employees").doc(employeeId).delete();
    },

    async listAgents(tenantId) {
      const snapshot = await db
        .collection("employees")
        .where("tenantId", "==", tenantId)
        .where("role", "==", "agent")
        .get();
      return snapshot.docs.map((doc) => ({ id: doc.id, ...doc.data() }));
    },

    appendAuditLog(entry) {
      db.collection("audit_logs").add({ ...entry, timestamp: new Date().toISOString() }).catch(() => {});
    },
  };
}

async function safeOrderedQuery(
  col,
  field,
  value,
  orderField,
  orderDir,
  limit,
) {
  try {
    let q = col.where(field, "==", value).orderBy(orderField, orderDir);
    if (limit) q = q.limit(limit);
    return await q.get();
  } catch (error) {
    if (isIndexError(error)) {
      let q = col.where(field, "==", value);
      if (limit) q = q.limit(limit);
      const snapshot = await q.get();
      const docs = [];
      snapshot.forEach((doc) => docs.push(doc));
      docs.sort((a, b) => {
        const av = a.data()[orderField] || 0;
        const bv = b.data()[orderField] || 0;
        return orderDir === "desc" ? bv - av : av - bv;
      });
      return {
        forEach(cb) {
          docs.forEach(cb);
        },
        docs,
      };
    }
    throw error;
  }
}

function isIndexError(error) {
  const code = error?.code;
  const msg = error?.message || "";
  return (
    code === 9 ||
    code === "failed-precondition" ||
    msg.includes("index") ||
    msg.includes("requires an index") ||
    msg.includes("FAILED_PRECONDITION")
  );
}
