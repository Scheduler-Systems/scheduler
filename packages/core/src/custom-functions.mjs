export function createCustomFunctions(store) {
  return {
    getSchedulesWithEmptyEmployees() {
      const allSchedules = store.listSchedules("_all") || [];
      const empty = [];
      for (const s of allSchedules) {
        if (!s.employees || s.employees.length === 0) {
          empty.push({ id: s.id });
        }
      }
      return { schedules: empty, total: empty.length };
    },

    deleteSchedulesWithEmptyEmployees() {
      const allSchedules = store.listSchedules("_all") || [];
      const deletedIds = [];
      for (const s of allSchedules) {
        if (!s.employees || s.employees.length === 0) {
          store.deleteSchedule(s.tenantId, s.id);
          deletedIds.push(s.id);
        }
      }
      if (deletedIds.length === 0) {
        return { message: "No schedules with empty employees array found." };
      }
      return {
        message: "Successfully deleted schedules with empty employees array.",
        deletedSchedules: deletedIds,
        totalDeleted: deletedIds.length,
      };
    },

    getSchedulesWithSubmissionDeadlineSet() {
      const allSchedules = store.listSchedules("_all") || [];
      const result = [];
      for (const s of allSchedules) {
        const deadline = s.scheduleSettings?.submission_deadline?.weekday;
        if (deadline != null) {
          result.push({ id: s.id, weekday: deadline });
        }
      }
      return { schedules: result, total: result.length };
    },

    updateWeekdaysToUpperCase() {
      const allSchedules = store.listSchedules("_all") || [];
      let updated = 0;
      for (const s of allSchedules) {
        const deadline = s.scheduleSettings?.submission_deadline;
        if (deadline?.weekday && deadline.weekday !== deadline.weekday.toUpperCase()) {
          const updatedSchedule = {
            ...s,
            scheduleSettings: {
              ...s.scheduleSettings,
              submission_deadline: { ...deadline, weekday: deadline.weekday.toUpperCase() },
            },
            updatedAt: new Date().toISOString(),
          };
          store.putSchedule(updatedSchedule);
          updated++;
        }
      }
      return { updated };
    },

    getActiveEntitlementsWeb() {
      return { success: true, entitlements: [] };
    },

    sendWelcomeEmail(userData) {
      const mailData = {
        to: [userData.email],
        message: {
          subject: "Welcome to Scheduler!",
          text: "Welcome to Scheduler! We're excited to have you on board.",
          html: "<h1>Welcome to Scheduler!</h1><p>We're excited to have you on board.</p>",
        },
      };
      return { queued: true, mailData };
    },

    trackWebhookEvents(eventData) {
      if (eventData.type === "INITIAL_PURCHASE") {
        return { tracked: true, eventType: eventData.type, userId: eventData.user_id };
      }
      return { tracked: false, reason: "not_initial_purchase" };
    },
  };
}
