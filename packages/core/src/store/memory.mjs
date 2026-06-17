export function createMemoryStore() {
  const schedules = new Map();
  const imports = new Map();
  const employees = new Map();
  const attendance = new Map();
  const shiftRequests = new Map();
  const builtSchedules = new Map();
  const chatMessages = new Map();
  const notifications = new Map();
  const stationEntitlements = new Map();
  const auditLogs = [];
  const drafts = new Map();
  const requests = new Map();
  const availability = new Map();
  const approvals = new Map();

  return {
    listSchedules(tenantId) {
      return [...schedules.values()].filter((s) => s.tenantId === tenantId);
    },
    putSchedule(schedule) {
      schedules.set(`${schedule.tenantId}:${schedule.id}`, schedule);
      return schedule;
    },
    getSchedule(tenantId, scheduleId) {
      return schedules.get(`${tenantId}:${scheduleId}`) ?? null;
    },
    deleteSchedule(tenantId, scheduleId) {
      schedules.delete(`${tenantId}:${scheduleId}`);
    },
    putImport(result) {
      imports.set(`${result.tenantId}:${result.importId}`, result);
      return result;
    },
    getImport(importId) {
      for (const imp of imports.values()) {
        if (imp.importId === importId) return imp;
      }
      return null;
    },
    listImports(tenantId) {
      return [...imports.values()].filter((i) => i.tenantId === tenantId)
        .sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0));
    },
    putDraft(draft) {
      drafts.set(draft.id, draft);
      return draft;
    },
    getDraft(id) {
      return drafts.get(id) ?? null;
    },
    deleteDraft(id) {
      drafts.delete(id);
    },
    putAvailability(entry) {
      availability.set(entry.id, entry);
      return entry;
    },
    getAvailability(id) {
      return availability.get(id) ?? null;
    },
    putRequest(req) {
      requests.set(req.id, req);
      return req;
    },
    getRequest(id) {
      return requests.get(id) ?? null;
    },
    putApproval(approval) {
      approvals.set(approval.id, approval);
      return approval;
    },

    // Employee management
    listEmployees(tenantId) {
      return [...employees.values()].filter((e) => e.tenantId === tenantId);
    },
    putEmployee(employee) {
      employees.set(`${employee.tenantId}:${employee.id}`, employee);
      return employee;
    },
    getEmployee(tenantId, employeeId) {
      return employees.get(`${tenantId}:${employeeId}`) ?? null;
    },
    deleteEmployee(tenantId, employeeId) {
      employees.delete(`${tenantId}:${employeeId}`);
    },
    listAgents(tenantId) {
      return [...employees.values()].filter(
        (e) => e.tenantId === tenantId && e.role === "agent"
      );
    },

    // Attendance
    putAttendance(record) {
      const key = `${record.tenantId}:${record.employeeId}:${record.date}`;
      attendance.set(key, record);
      return record;
    },
    getAttendance(tenantId, employeeId, date) {
      return attendance.get(`${tenantId}:${employeeId}:${date}`) ?? null;
    },
    listAttendanceByEmployee(tenantId, employeeId, startDate, endDate) {
      return [...attendance.values()].filter(
        (a) => a.tenantId === tenantId && a.employeeId === employeeId
      );
    },

    // Shift requests / priority requests
    putShiftRequest(request) {
      shiftRequests.set(`${request.tenantId}:${request.id}`, request);
      return request;
    },
    getShiftRequest(tenantId, requestId) {
      return shiftRequests.get(`${tenantId}:${requestId}`) ?? null;
    },
    listShiftRequests(tenantId, scheduleId) {
      return [...shiftRequests.values()].filter(
        (r) => r.tenantId === tenantId && r.scheduleId === scheduleId
      );
    },

    // Built schedules
    putBuiltSchedule(schedule) {
      builtSchedules.set(`${schedule.tenantId}:${schedule.id}`, schedule);
      return schedule;
    },
    getBuiltSchedule(tenantId, scheduleId, builtId) {
      return builtSchedules.get(`${tenantId}:${builtId}`) ?? null;
    },
    listBuiltSchedules(tenantId, scheduleId) {
      return [...builtSchedules.values()].filter(
        (b) => b.tenantId === tenantId && b.scheduleId === scheduleId
      );
    },

    // Chat messages
    putChatMessage(message) {
      chatMessages.set(`${message.tenantId}:${message.id}`, message);
      return message;
    },
    listChatMessages(tenantId, chatId, limit = 50) {
      return [...chatMessages.values()]
        .filter((m) => m.tenantId === tenantId && m.chatId === chatId)
        .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
        .slice(-limit);
    },

    // Notifications
    putNotification(notification) {
      notifications.set(`${notification.tenantId}:${notification.id}`, notification);
      return notification;
    },
    listNotifications(tenantId, userId) {
      return [...notifications.values()]
        .filter((n) => n.tenantId === tenantId && n.toUserId === userId)
        .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    },
    deleteNotification(tenantId, notificationId) {
      notifications.delete(`${tenantId}:${notificationId}`);
    },

    // Station entitlements
    putStationEntitlement(entitlement) {
      stationEntitlements.set(`${entitlement.tenantId}:${entitlement.stationId}`, entitlement);
      return entitlement;
    },
    getStationEntitlement(tenantId, stationId) {
      return stationEntitlements.get(`${tenantId}:${stationId}`) ?? null;
    },

    // Audit
    appendAuditLog(entry) {
      auditLogs.push({ ...entry, timestamp: new Date().toISOString() });
      return entry;
    },
    listAuditLogs(tenantId) {
      return auditLogs.filter((e) => e.tenantId === tenantId);
    }
  };
}
