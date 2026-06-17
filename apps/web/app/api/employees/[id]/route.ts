import { NextRequest } from "next/server";
import { z } from "zod";
import { withAuth } from "@/lib/api/auth";
import { corsResponse, corsErrorResponse } from "@/lib/api/cors";
import { getAdminDb } from "@/lib/firebase/server";
import { employeeUpdateSchema } from "@/types/api";
import { fromFirestoreUser, UserFirestore } from "@/types/user";
import { sharesScheduleWith } from "@/lib/server/schedule-contacts";

const USERS_COLLECTION = "users";

// SECURITY (#51 item 8 — by-id IDOR). This route uses the Admin SDK, which
// bypasses Firestore rules, so before this hardening any authenticated user
// could read ANY user's profile by uid and rename/delete ANY user doc. We now
// mirror the `users` rules: read requires the target be the caller or a
// schedule co-member; updates are self-only; delete is denied (the rule is
// `allow delete: if false`). A harvested uid is no longer a read/write oracle.

async function getEmployee(
  request: NextRequest,
  auth: { uid: string; email: string | null },
  params: Record<string, string>
) {
  const { id } = params;

  if (!id) {
    return corsErrorResponse("Employee ID required", 400, request);
  }

  try {
    const db = getAdminDb();

    // Authorize: caller may read only themselves or a schedule co-member.
    if (!(await sharesScheduleWith(db, auth.uid, id))) {
      return corsErrorResponse("Forbidden", 403, request);
    }

    const doc = await db.collection(USERS_COLLECTION).doc(id).get();

    if (!doc.exists) {
      return corsErrorResponse("Employee not found", 404, request);
    }

    const data = doc.data() as UserFirestore;
    const user = fromFirestoreUser(doc.id, data);

    return corsResponse({ success: true, data: user }, 200, request);
  } catch (error) {
    console.error("Error fetching employee:", error);
    return corsErrorResponse("Failed to fetch employee", 500, request);
  }
}

async function updateEmployee(
  request: NextRequest,
  auth: { uid: string; email: string | null },
  params: Record<string, string>
) {
  const { id } = params;

  if (!id) {
    return corsErrorResponse("Employee ID required", 400, request);
  }

  // Self-only — mirrors `allow update: if isOwner(userId)`. A user may not
  // rename or re-role another user's profile via this route.
  if (id !== auth.uid) {
    return corsErrorResponse("Forbidden", 403, request);
  }

  try {
    const body = await request.json();
    const data = employeeUpdateSchema.parse(body);

    const docRef = getAdminDb().collection(USERS_COLLECTION).doc(id);
    const doc = await docRef.get();

    if (!doc.exists) {
      return corsErrorResponse("Employee not found", 404, request);
    }

    const updateData: Partial<UserFirestore> = {};

    if (data.employeeName) updateData.display_name = data.employeeName;
    if (data.employeeRole) updateData.role = data.employeeRole;

    await docRef.update(updateData);

    return corsResponse({ success: true, message: "Employee updated" }, 200, request);
  } catch (error) {
    if (error instanceof z.ZodError) {
      return corsErrorResponse(
        `Validation error: ${error.errors.map((e) => e.message).join(", ")}`,
        400,
        request
      );
    }

    console.error("Error updating employee:", error);
    return corsErrorResponse("Failed to update employee", 500, request);
  }
}

async function deleteEmployee(
  request: NextRequest,
  _auth: { uid: string; email: string | null },
  params: Record<string, string>
) {
  const { id } = params;

  if (!id) {
    return corsErrorResponse("Employee ID required", 400, request);
  }

  // Deleting a user doc is denied for clients — mirrors the Firestore rule
  // `allow delete: if false`. Account deletion is an Admin-side operation.
  return corsErrorResponse("Deleting users is not permitted", 403, request);
}

export const GET = withAuth(getEmployee);
export const PUT = withAuth(updateEmployee);
export const PATCH = withAuth(updateEmployee);
export const DELETE = withAuth(deleteEmployee);
