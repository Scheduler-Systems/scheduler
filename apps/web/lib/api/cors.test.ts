import { describe, it, expect } from "vitest";
import { corsHeaders, handleCorsPreflight, corsResponse, corsErrorResponse } from "./cors";

function makeRequest(origin?: string): Request {
  const headers = new Headers();
  if (origin) headers.set("origin", origin);
  return new Request("http://localhost:3000/api/test", { headers });
}

describe("corsHeaders", () => {
  it("returns basic CORS headers for non-whitelisted origin", () => {
    const headers = corsHeaders("https://evil.com");
    expect(headers).not.toHaveProperty("Access-Control-Allow-Origin");
    expect(headers).toHaveProperty("Access-Control-Allow-Methods");
    expect(headers).toHaveProperty("Access-Control-Allow-Headers");
  });

  it("returns origin-specific headers for whitelisted origin", () => {
    const headers = corsHeaders("http://localhost:3000");
    expect(headers).toHaveProperty("Access-Control-Allow-Origin", "http://localhost:3000");
    expect(headers).toHaveProperty("Access-Control-Allow-Credentials", "true");
  });

  it("returns origin-specific headers for production origin", () => {
    const headers = corsHeaders("https://scheduler.systems");
    expect(headers).toHaveProperty("Access-Control-Allow-Origin", "https://scheduler.systems");
    expect(headers).toHaveProperty("Access-Control-Allow-Credentials", "true");
  });

  it("handles null origin", () => {
    const headers = corsHeaders(null);
    expect(headers).not.toHaveProperty("Access-Control-Allow-Origin");
  });
});

describe("handleCorsPreflight", () => {
  it("returns 204 with CORS headers", () => {
    const req = makeRequest("http://localhost:3000");
    const res = handleCorsPreflight(req);
    expect(res.status).toBe(204);
    expect(res.body).toBeNull();
    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("http://localhost:3000");
  });

  it("returns 204 without origin for non-whitelisted origin", () => {
    const req = makeRequest("https://bad.com");
    const res = handleCorsPreflight(req);
    expect(res.status).toBe(204);
    expect(res.headers.get("Access-Control-Allow-Origin")).toBeNull();
  });
});

describe("corsResponse", () => {
  it("returns JSON with CORS headers", async () => {
    const req = makeRequest("http://localhost:3000");
    const res = corsResponse({ data: "hello" }, 200, req);
    expect(res.status).toBe(200);
    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("http://localhost:3000");

    const body = await res.json();
    expect(body).toEqual({ data: "hello" });
  });

  it("uses custom status code", () => {
    const req = makeRequest();
    const res = corsResponse({ created: true }, 201, req);
    expect(res.status).toBe(201);
  });
});

describe("corsErrorResponse", () => {
  it("returns error JSON with CORS headers", async () => {
    const req = makeRequest("http://localhost:3000");
    const res = corsErrorResponse("Not found", 404, req);
    expect(res.status).toBe(404);

    const body = await res.json();
    expect(body).toEqual({ success: false, error: "Not found" });
  });

  it("has default status 500", () => {
    const req = makeRequest();
    const res = corsErrorResponse("Oops", undefined, req);
    expect(res.status).toBe(500);
  });
});
