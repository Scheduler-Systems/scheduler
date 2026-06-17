import { NextRequest } from "next/server";
import { handleCorsPreflight, corsResponse, corsErrorResponse } from "@/lib/api/cors";
import { checkRateLimit, getRateLimitKey, rateLimitConfigs } from "@/lib/api/rate-limit";
import { getClientIdentifier } from "@/lib/api/auth";
import { getAdminDb } from "@/lib/firebase/server";
import { webhookEventSchema } from "@/types/api";

const WEBHOOK_EVENTS_COLLECTION = "webhook_events";

function verifyWebhookSignature(request: NextRequest, body: string): boolean {
  const signature = request.headers.get("x-webhook-signature");
  const secret = process.env.WEBHOOK_SECRET;
  
  if (!signature || !secret) {
    return false;
  }
  
  return signature === secret;
}

export async function OPTIONS(request: NextRequest) {
  return handleCorsPreflight(request);
}

export async function POST(request: NextRequest) {
  const clientId = getClientIdentifier(request);
  const rateKey = getRateLimitKey(clientId, "webhook");
  const rateResult = checkRateLimit(rateKey, rateLimitConfigs.webhook);
  
  if (!rateResult.allowed) {
    return corsErrorResponse("Rate limit exceeded", 429, request);
  }
  
  try {
    const body = await request.text();
    
    if (!verifyWebhookSignature(request, body)) {
      return corsErrorResponse("Invalid webhook signature", 401, request);
    }
    
    const payload = JSON.parse(body);
    const event = webhookEventSchema.parse(payload);
    
    const eventData = {
      event_type: event.event,
      data: event.data,
      timestamp: event.timestamp ?? Date.now(),
      processed: false,
      created_at: new Date(),
    };
    
    await getAdminDb().collection(WEBHOOK_EVENTS_COLLECTION).add(eventData);
    
    return corsResponse(
      { success: true, message: "Webhook received" },
      200,
      request
    );
  } catch (error) {
    console.error("Webhook error:", error);
    return corsErrorResponse(
      error instanceof Error ? error.message : "Webhook processing failed",
      400,
      request
    );
  }
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const eventType = searchParams.get("eventType");
  const limit = Math.min(parseInt(searchParams.get("limit") ?? "50"), 100);
  
  try {
    let query = getAdminDb()
      .collection(WEBHOOK_EVENTS_COLLECTION)
      .orderBy("created_at", "desc")
      .limit(limit);
    
    if (eventType) {
      query = query.where("event_type", "==", eventType);
    }
    
    const snapshot = await query.get();
    
    const events = snapshot.docs.map((doc) => ({
      id: doc.id,
      ...doc.data(),
    }));
    
    return corsResponse({ success: true, events }, 200, request);
  } catch (error) {
    console.error("Error fetching webhooks:", error);
    return corsErrorResponse("Failed to fetch webhooks", 500, request);
  }
}
