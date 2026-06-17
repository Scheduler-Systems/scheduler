import { jsonResponse, readJson } from "../middleware/auth.mjs";

export function createChatRoutes() {
  return {
    matchRoute(method, parts, { store }) {
      const tenantId = parts[2];

      // POST /v1/tenants/{tenantId}/chats/{chatId}/messages
      if (method === "POST" && parts.length === 6 && parts[3] === "chats" && parts[5] === "messages") {
        return {
          params: { tenantId, chatId: parts[4] },
          handler: async ({ request, params, actor }) => {
            const body = await readJson(request);
            const message = {
              id: body.id ?? `msg_${Date.now()}`,
              tenantId: params.tenantId,
              chatId: params.chatId,
              senderId: actor.userId,
              text: body.text,
              timestamp: new Date().toISOString(),
            };
            store.putChatMessage(message);
            store.appendAuditLog({ tenantId: params.tenantId, action: "chat_message_send", chatId: params.chatId, actor: actor.userId });
            return jsonResponse(201, message);
          },
        };
      }

      // GET /v1/tenants/{tenantId}/chats/{chatId}/messages
      if (method === "GET" && parts.length === 6 && parts[3] === "chats" && parts[5] === "messages") {
        return {
          params: { tenantId, chatId: parts[4] },
          handler: async ({ request, params }) => {
            const url = new URL(request.url);
            const limit = parseInt(url.searchParams.get("limit") ?? "50", 10);
            const messages = store.listChatMessages(params.tenantId, params.chatId, limit);
            return jsonResponse(200, { items: messages, chatId: params.chatId });
          },
        };
      }

      return null;
    },
  };
}
