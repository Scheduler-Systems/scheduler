import { jsonResponse, readJson } from "../middleware/auth.mjs";

export function createNotificationRoutes() {
  return {
    matchRoute(method, parts, { store }) {
      const tenantId = parts[2];

      // GET /v1/tenants/{tenantId}/notifications
      if (method === "GET" && parts.length === 4 && parts[3] === "notifications") {
        return {
          params: { tenantId },
          handler: async ({ request, params, actor }) => {
            const notifications = store.listNotifications(params.tenantId, actor.userId);
            return jsonResponse(200, { items: notifications });
          },
        };
      }

      // POST /v1/tenants/{tenantId}/notifications
      if (method === "POST" && parts.length === 4 && parts[3] === "notifications") {
        return {
          params: { tenantId },
          handler: async ({ request, params, actor }) => {
            const body = await readJson(request);
            const notification = {
              id: body.id ?? `notif_${Date.now()}`,
              tenantId: params.tenantId,
              toUserId: body.toUserId,
              title: body.title,
              body: body.body,
              type: body.type ?? "info",
              read: false,
              createdAt: new Date().toISOString(),
              createdBy: actor.userId,
            };
            store.putNotification(notification);
            store.appendAuditLog({ tenantId: params.tenantId, action: "notification_create", notificationId: notification.id, actor: actor.userId });
            return jsonResponse(201, notification);
          },
        };
      }

      // PATCH /v1/tenants/{tenantId}/notifications/{notificationId}
      if (method === "PATCH" && parts.length === 5 && parts[3] === "notifications") {
        return {
          params: { tenantId, notificationId: parts[4] },
          handler: async ({ request, params, actor }) => {
            const body = await readJson(request);
            return jsonResponse(200, {
              id: params.notificationId,
              tenantId: params.tenantId,
              read: body.read ?? true,
              updatedAt: new Date().toISOString(),
            });
          },
        };
      }

      // DELETE /v1/tenants/{tenantId}/notifications/{notificationId}
      if (method === "DELETE" && parts.length === 5 && parts[3] === "notifications") {
        return {
          params: { tenantId, notificationId: parts[4] },
          handler: async ({ params, actor }) => {
            store.deleteNotification(params.tenantId, params.notificationId);
            store.appendAuditLog({ tenantId: params.tenantId, action: "notification_delete", notificationId: params.notificationId, actor: actor.userId });
            return jsonResponse(200, { deleted: params.notificationId });
          },
        };
      }

      return null;
    },
  };
}
