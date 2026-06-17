import { NextRequest } from "next/server";
import { z } from "zod";
import { withAuth } from "@/lib/api/auth";
import { corsResponse, corsErrorResponse } from "@/lib/api/cors";
import { getAdminDb } from "@/lib/firebase/server";
import { scheduleUpdateSchema } from "@/types/api";
import { fromFirestoreSchedule, ScheduleFirestore } from "@/types/schedule";

const SCHEDULES_COLLECTION = "schedules";

async function getSchedule(
  request: NextRequest,
  auth: { uid: string; email: string | null },
  params: Record<string, string>
) {
  const { id } = params;
  
  if (!id) {
    return corsErrorResponse("Schedule ID required", 400, request);
  }
  
  try {
    const doc = await getAdminDb().collection(SCHEDULES_COLLECTION).doc(id).get();
    
    if (!doc.exists) {
      return corsErrorResponse("Schedule not found", 404, request);
    }
    
    const data = doc.data() as ScheduleFirestore;
    const schedule = fromFirestoreSchedule(doc.id, data);
    
    return corsResponse({ success: true, data: schedule }, 200, request);
  } catch (error) {
    console.error("Error fetching schedule:", error);
    return corsErrorResponse("Failed to fetch schedule", 500, request);
  }
}

async function updateSchedule(
  request: NextRequest,
  auth: { uid: string; email: string | null },
  params: Record<string, string>
) {
  const { id } = params;
  
  if (!id) {
    return corsErrorResponse("Schedule ID required", 400, request);
  }
  
  try {
    const body = await request.json();
    const data = scheduleUpdateSchema.parse(body);
    
    const docRef = getAdminDb().collection(SCHEDULES_COLLECTION).doc(id);
    const doc = await docRef.get();
    
    if (!doc.exists) {
      return corsErrorResponse("Schedule not found", 404, request);
    }
    
    const updateData: Partial<ScheduleFirestore> = {};
    
    if (data.scheduleName) updateData.schedule_name = data.scheduleName;
    if (data.employees) {
      updateData.employees = data.employees.map((e) => ({
        employee_name: e.employeeName,
        employee_id: e.employeeId,
        employee_role: e.employeeRole,
        employee_priority: e.employeePriority,
        employee_availability: e.employeeAvailability,
      }));
    }
    if (data.currentPriorities) updateData.current_priorities = data.currentPriorities;
    if (data.scheduleSettings) {
      updateData.schedule_settings = {
        shift_hours: data.scheduleSettings.shiftHours,
        timezone: data.scheduleSettings.timezone,
        start_date: data.scheduleSettings.startDate
          ? new Date(data.scheduleSettings.startDate) as unknown as never
          : undefined,
        end_date: data.scheduleSettings.endDate
          ? new Date(data.scheduleSettings.endDate) as unknown as never
          : undefined,
      };
    }
    
    await docRef.update(updateData);
    
    return corsResponse({ success: true, message: "Schedule updated" }, 200, request);
  } catch (error) {
    if (error instanceof z.ZodError) {
      return corsErrorResponse(
        `Validation error: ${error.errors.map((e) => e.message).join(", ")}`,
        400,
        request
      );
    }
    
    console.error("Error updating schedule:", error);
    return corsErrorResponse("Failed to update schedule", 500, request);
  }
}

async function deleteSchedule(
  request: NextRequest,
  auth: { uid: string; email: string | null },
  params: Record<string, string>
) {
  const { id } = params;
  
  if (!id) {
    return corsErrorResponse("Schedule ID required", 400, request);
  }
  
  try {
    const docRef = getAdminDb().collection(SCHEDULES_COLLECTION).doc(id);
    const doc = await docRef.get();
    
    if (!doc.exists) {
      return corsErrorResponse("Schedule not found", 404, request);
    }
    
    await docRef.delete();
    
    return corsResponse({ success: true, message: "Schedule deleted" }, 200, request);
  } catch (error) {
    console.error("Error deleting schedule:", error);
    return corsErrorResponse("Failed to delete schedule", 500, request);
  }
}

export const GET = withAuth(getSchedule);
export const PUT = withAuth(updateSchedule);
export const PATCH = withAuth(updateSchedule);
export const DELETE = withAuth(deleteSchedule);
