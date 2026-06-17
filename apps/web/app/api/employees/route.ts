import { NextRequest } from "next/server";
import { z } from "zod";
import { withAuth } from "@/lib/api/auth";
import { corsResponse, corsErrorResponse } from "@/lib/api/cors";
import { getAdminDb } from "@/lib/firebase/server";
import { employeeCreateSchema, paginationSchema } from "@/types/api";
import { fromFirestoreUser, UserFirestore } from "@/types/user";
import {
  isCallerMemberOfSchedule,
  getScheduleMemberUids,
} from "@/lib/server/schedule-contacts";

const USERS_COLLECTION = "users";

async function getEmployeeList(
  request: NextRequest,
  auth: { uid: string; email: string | null },
  params: Record<string, string>
) {
  const { searchParams } = new URL(request.url);

  // SECURITY (#51 item 8 — cross-org user enumeration). Previously this returned
  // the ENTIRE `users` collection when no scheduleId was supplied (a direct
  // global-directory enumeration endpoint), and when one WAS supplied it queried
  // a non-existent `schedules_involved` array field AND never checked the caller
  // belonged to that schedule (an IDOR — read any schedule's roster). Now a
  // scheduleId is REQUIRED (checked first, fail-fast), the caller must be a
  // verified member of it, and only that schedule's roster is returned (derived
  // from the real membership index).
  const scheduleId = searchParams.get("scheduleId");
  if (!scheduleId) {
    return corsErrorResponse("scheduleId is required", 400, request);
  }

  // Coerce absent params to undefined so the schema's defaults apply — a bare
  // `searchParams.get` yields null, which paginationSchema rejects.
  const { page, pageSize } = paginationSchema.parse({
    page: searchParams.get("page") ?? undefined,
    pageSize: searchParams.get("pageSize") ?? undefined,
  });

  try {
    const db = getAdminDb();

    const isMember = await isCallerMemberOfSchedule(db, auth.uid, scheduleId);
    if (!isMember) {
      return corsErrorResponse("Forbidden", 403, request);
    }

    const memberUids = await getScheduleMemberUids(db, scheduleId);
    const allItems = memberUids.length
      ? (
          await db.getAll(
            ...memberUids.map((uid) =>
              db.collection(USERS_COLLECTION).doc(uid)
            )
          )
        )
          .filter((doc) => doc.exists)
          .map((doc) =>
            fromFirestoreUser(doc.id, doc.data() as UserFirestore)
          )
      : [];

    const start = (page - 1) * pageSize;
    const items = allItems.slice(start, start + pageSize);

    return corsResponse(
      {
        items,
        total: allItems.length,
        page,
        pageSize,
        hasMore: start + pageSize < allItems.length,
      },
      200,
      request
    );
  } catch (error) {
    console.error("Error fetching employees:", error);
    return corsErrorResponse("Failed to fetch employees", 500, request);
  }
}

async function createEmployee(
  request: NextRequest,
  auth: { uid: string; email: string | null },
  params: Record<string, string>
) {
  try {
    const body = await request.json();
    const data = employeeCreateSchema.parse(body);
    
    const userData: UserFirestore = {
      display_name: data.employeeName,
      uid: data.employeeId,
      role: data.employeeRole,
      created_time: new Date() as unknown as never,
    };
    
    const docRef = await getAdminDb().collection(USERS_COLLECTION).add(userData);
    
    return corsResponse({ success: true, id: docRef.id }, 201, request);
  } catch (error) {
    if (error instanceof z.ZodError) {
      return corsErrorResponse(
        `Validation error: ${error.errors.map((e) => e.message).join(", ")}`,
        400,
        request
      );
    }
    
    console.error("Error creating employee:", error);
    return corsErrorResponse("Failed to create employee", 500, request);
  }
}

export const GET = withAuth(getEmployeeList);
export const POST = withAuth(createEmployee);
