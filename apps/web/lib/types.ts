import type { DocumentReference, Timestamp } from "firebase/firestore";

export interface RoleStruct {
  is_creator: boolean;
  is_admin: boolean;
  is_worker: boolean;
}

export interface EmployeeDetails {
  employee_name: string;
  employee_email: string;
  employee_phone: string;
  role: RoleStruct;
  user_ref: DocumentReference | null;
}

// Matches Flutter's SubmissionDeadlineStruct shape. The Flutter app writes:
//   time: Timestamp (when the deadline is; null if unset)
//   is_activated: bool (whether enforcement is on)
//   weekday: enum string ("SUNDAY"..."SATURDAY")
// Older Next.js docs stored this as a bare Timestamp; parsing tolerates both.
export interface SubmissionDeadline {
  time: Timestamp | null;
  is_activated: boolean;
  weekday: string;
}

export interface ScheduleSettings {
  enabled_shifts: string[];
  num_of_stations: number;
  submission_deadline: SubmissionDeadline | Timestamp | null;
  morning_hours?: string;
  noon_hours?: string;
  night_hours?: string;
}

export interface Schedule {
  id: string;
  schedule_name: string;
  employees: EmployeeDetails[];
  current_priorities: string[];
  schedule_settings: ScheduleSettings | null;
  sid: string;
  next_schedule: string[];
}

export interface ScheduleInvolved {
  schedules_collection_ref: DocumentReference;
  schedule_name: string;
}

export interface ScheduleRow {
  stringList: string[];
}

export interface BuiltSchedule {
  id: string;
  schedule: ScheduleRow[];
  first_weekday: string;
  last_weekday: string;
  first_weekday_datetime: Timestamp | null;
  last_weekday_datetime: Timestamp | null;
  time_created: Timestamp;
  current_priorities: string[];
}

export interface UserRecord {
  uid: string;
  email: string;
  display_name: string;
  role: RoleStruct | null;
  is_premium: boolean;
  title: string;
  phone_number: string;
}
