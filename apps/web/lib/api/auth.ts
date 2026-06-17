import { NextRequest, NextResponse } from "next/server";
import { verifySessionCookie } from "@/lib/firebase/server";
import { corsErrorResponse, handleCorsPreflight } from "./cors";
import { checkRateLimit, getRateLimitKey, rateLimitConfigs } from "./rate-limit";

export interface AuthContext {
  uid: string;
  email: string | null;
  authenticated: boolean;
}

export async function getAuthContext(request: NextRequest): Promise<AuthContext | null> {
  const sessionCookie = request.cookies.get("session")?.value;
  
  if (!sessionCookie) {
    return null;
  }
  
  const result = await verifySessionCookie(sessionCookie);
  
  if (!result.valid || !result.uid) {
    return null;
  }
  
  return {
    uid: result.uid,
    email: result.email ?? null,
    authenticated: true,
  };
}

export function getClientIdentifier(request: NextRequest): string {
  const forwarded = request.headers.get("x-forwarded-for");
  const ip = forwarded?.split(",")[0]?.trim() ?? "unknown";
  const userAgent = request.headers.get("user-agent") ?? "unknown";
  return `${ip}:${userAgent.slice(0, 50)}`;
}

type RouteHandler = (
  request: NextRequest,
  context: AuthContext,
  params: Record<string, string>
) => Promise<NextResponse>;

interface MiddlewareOptions {
  requireAuth: boolean;
  rateLimitConfig: keyof typeof rateLimitConfigs;
}

export function withAuth(
  handler: RouteHandler,
  options: MiddlewareOptions = { requireAuth: true, rateLimitConfig: "api" }
): (request: NextRequest, context: { params: Promise<Record<string, string>> }) => Promise<NextResponse> {
  return async (request: NextRequest, context: { params: Promise<Record<string, string>> }) => {
    if (request.method === "OPTIONS") {
      return handleCorsPreflight(request);
    }
    
    const clientId = getClientIdentifier(request);
    const route = new URL(request.url).pathname;
    const rateKey = getRateLimitKey(clientId, route);
    const rateResult = checkRateLimit(rateKey, rateLimitConfigs[options.rateLimitConfig]);
    
    if (!rateResult.allowed) {
      return corsErrorResponse("Rate limit exceeded", 429, request);
    }
    
    const auth = await getAuthContext(request);
    
    if (options.requireAuth && !auth) {
      return corsErrorResponse("Unauthorized", 401, request);
    }
    
    const params = await context.params;
    return handler(request, auth!, params);
  };
}

export function optionalAuth(
  handler: RouteHandler
): (request: NextRequest, context: { params: Promise<Record<string, string>> }) => Promise<NextResponse> {
  return withAuth(handler, { requireAuth: false, rateLimitConfig: "api" });
}
