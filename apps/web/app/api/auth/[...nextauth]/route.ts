import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { corsResponse, corsErrorResponse, handleCorsPreflight } from "@/lib/api/cors";
import { checkRateLimit, getRateLimitKey, rateLimitConfigs } from "@/lib/api/rate-limit";
import { createSessionCookie, revokeSession, getAdminAuth } from "@/lib/firebase/server";
import { getClientIdentifier } from "@/lib/api/auth";

const loginSchema = z.object({
  idToken: z.string().min(1),
  expiresIn: z.coerce.number().optional().default(604800000),
});

const registerSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
  displayName: z.string().min(1).max(100).optional(),
});

export async function OPTIONS(request: NextRequest) {
  return handleCorsPreflight(request);
}

export async function POST(request: NextRequest) {
  const clientId = getClientIdentifier(request);
  const rateKey = getRateLimitKey(clientId, "auth");
  const rateResult = checkRateLimit(rateKey, rateLimitConfigs.auth);
  
  if (!rateResult.allowed) {
    return corsErrorResponse("Rate limit exceeded", 429, request);
  }
  
  try {
    const body = await request.json();
    const action = request.nextUrl.searchParams.get("action");
    
    if (action === "login") {
      const { idToken, expiresIn } = loginSchema.parse(body);
      const sessionCookie = await createSessionCookie(idToken, expiresIn);
      
      const response = corsResponse(
        { success: true, message: "Session created" },
        200,
        request
      );
      
      response.cookies.set("session", sessionCookie, {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        maxAge: expiresIn / 1000,
        path: "/",
      });
      
      return response;
    }
    
    if (action === "register") {
      const { email, password, displayName } = registerSchema.parse(body);
      
      const userRecord = await getAdminAuth().createUser({
        email,
        password,
        displayName,
      });
      
      return corsResponse(
        { success: true, uid: userRecord.uid },
        201,
        request
      );
    }
    
    if (action === "logout") {
      const sessionCookie = request.cookies.get("session")?.value;
      
      if (sessionCookie) {
        try {
          const decoded = await getAdminAuth().verifySessionCookie(sessionCookie, false);
          await revokeSession(decoded.uid);
        } catch {
          // Session invalid, continue with logout
        }
      }
      
      const response = corsResponse(
        { success: true, message: "Logged out" },
        200,
        request
      );
      
      response.cookies.delete("session");
      return response;
    }
    
    return corsErrorResponse("Invalid action", 400, request);
  } catch (error) {
    if (error instanceof z.ZodError) {
      return corsErrorResponse(
        `Validation error: ${error.errors.map((e) => e.message).join(", ")}`,
        400,
        request
      );
    }
    
    console.error("Auth error:", error);
    return corsErrorResponse(
      error instanceof Error ? error.message : "Authentication failed",
      401,
      request
    );
  }
}

export async function GET(request: NextRequest) {
  const sessionCookie = request.cookies.get("session")?.value;
  
  if (!sessionCookie) {
    return corsResponse(
      { authenticated: false },
      200,
      request
    );
  }
  
  try {
    const decoded = await getAdminAuth().verifySessionCookie(sessionCookie, true);
    const user = await getAdminAuth().getUser(decoded.uid);
    
    return corsResponse(
      {
        authenticated: true,
        user: {
          uid: user.uid,
          email: user.email,
          displayName: user.displayName,
          photoURL: user.photoURL,
        },
      },
      200,
      request
    );
  } catch {
    const response = corsResponse(
      { authenticated: false },
      200,
      request
    );
    response.cookies.delete("session");
    return response;
  }
}
