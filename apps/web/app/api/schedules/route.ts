import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { withAuth } from "@/lib/api/auth";
import { corsResponse, corsErrorResponse } from "@/lib/api/cors";
import { getAdminDb } from "@/lib/firebase/server";
import { scheduleCreateSchema, scheduleUpdateSchema, paginationSchema } from "@/types/api";
import { fromFirestoreSchedule, ScheduleFirestore } from "@/types/schedule";

const SCHEDULES_COLLECTION = "schedules";

async function getScheduleList(
  request: NextRequest,
  auth: { uid: string; email: string | null },
  params: Record<string, string>
) {
  const { searchParams } = new URL(request.url);
  const { page, pageSize } = paginationSchema.parse({
    page: searchParams.get("page"),
    pageSize: searchParams.get("pageSize"),
  });
  
  try {
    const snapshot = await getAdminDb()
      .collection(SCHEDULES_COLLECTION)
      .where("employees", "array-contains", auth.uid)
      .orderBy("created_time", "desc")
      .offset((page - 1) * pageSize)
      .limit(pageSize + 1)
      .get();
    
    const items = snapshot.docs.slice(0, pageSize).map((doc) =>
      fromFirestoreSchedule(doc.id, doc.data() as ScheduleFirestore)
    );
    
    return corsResponse(
      {
        items,
        total: items.length,
        page,
        pageSize,
        hasMore: snapshot.docs.length > pageSize,
      },
      200,
      request
    );
  } catch (error) {
    console.error("Error fetching schedules:", error);
    return corsErrorResponse("Failed to fetch schedules", 500, request);
  }
}

async function createSchedule(
  request: NextRequest,
  auth: { uid: string; email: string | null },
  params: Record<string, string>
) {
  try {
    const body = await request.json();
    const data = scheduleCreateSchema.parse(body);
    
    const scheduleData: ScheduleFirestore = {
      schedule_name: data.scheduleName,
      employees: data.employees.map((e) => ({
        employee_name: e.employeeName,
        employee_id: e.employeeId,
        employee_role: e.employeeRole,
        employee_priority: e.employeePriority,
        employee_availability: e.employeeAvailability,
      })),
      current_priorities: data.currentPriorities,
      schedule_settings: {
        shift_hours: data.scheduleSettings.shiftHours,
        timezone: data.scheduleSettings.timezone,
        start_date: data.scheduleSettings.startDate
          ? new Date(data.scheduleSettings.startDate) as unknown as never
          : undefined,
        end_date: data.scheduleSettings.endDate
          ? new Date(data.scheduleSettings.endDate) as unknown as never
          : undefined,
      },
      sid: auth.uid,
    };
    
    const docRef = await getAdminDb().collection(SCHEDULES_COLLECTION).add(scheduleData);
    
    return corsResponse(
      { success: true, id: docRef.id },
      201,
      request
    );
  } catch (error) {
    if (error instanceof z.ZodError) {
      return corsErrorResponse(
        `Validation error: ${error.errors.map((e) => e.message).join(", ")}`,
        400,
        request
      );
    }
    
    console.error("Error creating schedule:", error);
    return corsErrorResponse("Failed to create schedule", 500, request);
  }
}

export const GET = withAuth(getScheduleList);
export const POST = withAuth(createSchedule);
