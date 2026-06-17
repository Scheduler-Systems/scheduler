import { z } from "zod";

export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
}

export const paginationSchema = z.object({
  page: z.coerce.number().int().min(1).default(1),
  pageSize: z.coerce.number().int().min(1).max(100).default(20),
});

export const scheduleCreateSchema = z.object({
  scheduleName: z.string().min(1).max(100),
  employees: z.array(z.object({
    employeeName: z.string().min(1),
    employeeId: z.string().min(1),
    employeeRole: z.enum(["manager", "worker"]),
    employeePriority: z.number().int().min(0),
    employeeAvailability: z.array(z.string()),
  })).min(1),
  currentPriorities: z.array(z.string()),
  scheduleSettings: z.object({
    shiftHours: z.object({
      morning: z.string(),
      noon: z.string(),
      night: z.string(),
    }),
    timezone: z.string(),
    startDate: z.string().optional(),
    endDate: z.string().optional(),
  }),
});

export const scheduleUpdateSchema = scheduleCreateSchema.partial();

export const employeeCreateSchema = z.object({
  employeeName: z.string().min(1).max(100),
  employeeId: z.string().min(1),
  employeeRole: z.enum(["manager", "worker"]),
  employeePriority: z.number().int().min(0),
  employeeAvailability: z.array(z.string()),
});

export const employeeUpdateSchema = employeeCreateSchema.partial();

export const webhookEventSchema = z.object({
  event: z.string(),
  data: z.record(z.unknown()),
  timestamp: z.number().optional(),
});
