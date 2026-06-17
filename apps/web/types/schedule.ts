import { Timestamp } from "firebase/firestore";

export interface EmployeeDetails {
  employeeName: string;
  employeeId: string;
  employeeRole: "manager" | "worker";
  employeePriority: number;
  employeeAvailability: string[];
}

export interface ScheduleSettings {
  shiftHours: {
    morning: string;
    noon: string;
    night: string;
  };
  timezone: string;
  startDate: Date | null;
  endDate: Date | null;
}

export interface Schedule {
  id: string;
  scheduleName: string;
  employees: EmployeeDetails[];
  currentPriorities: string[];
  scheduleSettings: ScheduleSettings;
  sid: string;
  nextSchedule: string[][];
}

export interface ScheduleFirestore {
  schedule_name?: string;
  employees?: EmployeeDetailsFirestore[];
  current_priorities?: string[];
  schedule_settings?: ScheduleSettingsFirestore;
  sid?: string;
  next_schedule?: string[][];
}

export interface EmployeeDetailsFirestore {
  employee_name?: string;
  employee_id?: string;
  employee_role?: string;
  employee_priority?: number;
  employee_availability?: string[];
}

export interface ScheduleSettingsFirestore {
  shift_hours?: {
    morning?: string;
    noon?: string;
    night?: string;
  };
  timezone?: string;
  start_date?: Timestamp;
  end_date?: Timestamp;
}

export function fromFirestoreSchedule(id: string, data: ScheduleFirestore): Schedule {
  return {
    id,
    scheduleName: data.schedule_name ?? "",
    employees: (data.employees ?? []).map((e) => ({
      employeeName: e.employee_name ?? "",
      employeeId: e.employee_id ?? "",
      employeeRole: (e.employee_role as EmployeeDetails["employeeRole"]) ?? "worker",
      employeePriority: e.employee_priority ?? 0,
      employeeAvailability: e.employee_availability ?? [],
    })),
    currentPriorities: data.current_priorities ?? [],
    scheduleSettings: {
      shiftHours: {
        morning: data.schedule_settings?.shift_hours?.morning ?? "07:00 - 15:00",
        noon: data.schedule_settings?.shift_hours?.noon ?? "15:00 - 23:00",
        night: data.schedule_settings?.shift_hours?.night ?? "23:00 - 07:00",
      },
      timezone: data.schedule_settings?.timezone ?? "UTC",
      startDate: data.schedule_settings?.start_date?.toDate() ?? null,
      endDate: data.schedule_settings?.end_date?.toDate() ?? null,
    },
    sid: data.sid ?? "",
    nextSchedule: data.next_schedule ?? [],
  };
}
