import { NextRequest, NextResponse } from "next/server";
import { withAuth, type AuthContext } from "@/lib/api/auth";
import { corsResponse, corsErrorResponse } from "@/lib/api/cors";
import { getAdminDb } from "@/lib/firebase/server";
import { getChatContactsFor } from "@/lib/server/schedule-contacts";

/**
 * GET /api/chat/contacts — the membership-scoped participant directory for the
 * /chat/new picker.
 *
 * SECURITY (#51 item 8). Replaces the client-side `subscribeToUsers` query,
 * which streamed the ENTIRE `users` collection (every name + email, every org)
 * to any signed-in browser. The set returned here is computed server-side from
 * the caller's *verified* uid — only users who share a schedule with the caller
 * — so the scope cannot be widened by a client parameter, and the global
 * directory is never exposed. The Firestore rule `users` list-deny closes the
 * same hole at the SDK boundary; this endpoint is how the feature keeps working
 * under that tightened rule.
 */
async function getContacts(
  request: NextRequest,
  auth: AuthContext
): Promise<NextResponse> {
  try {
    const items = await getChatContactsFor(getAdminDb(), auth.uid);
    return corsResponse({ items }, 200, request);
  } catch (error) {
    console.error("Error fetching chat contacts:", error);
    return corsErrorResponse("Failed to fetch contacts", 500, request);
  }
}

export const GET = withAuth(getContacts);
