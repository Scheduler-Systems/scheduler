import { NextResponse } from "next/server";

const allowedOrigins = [
  process.env.NEXT_PUBLIC_APP_URL,
  "http://localhost:3000",
  "https://scheduler.systems",
].filter(Boolean) as string[];

const allowedMethods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"];
const allowedHeaders = [
  "Content-Type",
  "Authorization",
  "X-Requested-With",
  "X-Request-ID",
  "X-Tenant-ID",
];
const exposedHeaders = ["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"];

export function corsHeaders(origin: string | null): HeadersInit {
  const headers: HeadersInit = {
    "Access-Control-Allow-Methods": allowedMethods.join(", "),
    "Access-Control-Allow-Headers": allowedHeaders.join(", "),
    "Access-Control-Expose-Headers": exposedHeaders.join(", "),
    "Access-Control-Max-Age": "86400",
  };
  
  if (origin && allowedOrigins.includes(origin)) {
    headers["Access-Control-Allow-Origin"] = origin;
    headers["Access-Control-Allow-Credentials"] = "true";
  }
  
  return headers;
}

export function handleCorsPreflight(request: Request): NextResponse {
  const origin = request.headers.get("origin");
  return new NextResponse(null, {
    status: 204,
    headers: corsHeaders(origin),
  });
}

export function corsResponse<T>(data: T, status: number = 200, request: Request): NextResponse {
  const origin = request.headers.get("origin");
  return NextResponse.json(data, {
    status,
    headers: corsHeaders(origin),
  });
}

export function corsErrorResponse(
  error: string,
  status: number = 500,
  request: Request
): NextResponse {
  const origin = request.headers.get("origin");
  return NextResponse.json(
    { success: false, error },
    { status, headers: corsHeaders(origin) }
  );
}
