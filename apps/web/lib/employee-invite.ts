"use client";

/**
 * Employee invite flow — the web port of Flutter's `add_employee_widget.dart`.
 *
 * Flutter source of truth:
 *   lib/production_pages/add_employee/add_employee_widget.dart
 *
 * The Flutter "Add Employee" screen does NOT write the employee directly into
 * the schedule. Instead it sends an *invitation*: it validates the email,
 * looks the invitee up by email, prevents duplicate invitations, writes a
 * `schedule_requests` doc with `is_add_request: true` /
 * `request_status: ADD_RQUEST_PENDING`, and (for invitees who already have an
 * account) fires a push notification. The invitee then accepts/declines from
 * their own device via /invites → `acceptScheduleInvite` (lib/requests.ts),
 * which performs the Flutter-parity 4-write batch CLIENT-SIDE: status +
 * users/{uid}/schedules_involved + schedule employees[] + schedule-chat users[].
 * (NO Cloud Function is involved — an earlier comment here claimed one was,
 * which masked the 2026-06-11 P0 where accept never created membership.)
 *
 * This module reproduces that orchestration so the Next.js UI matches the
 * Flutter B2B paradigm instead of the previous direct-write `addEmployee`.
 *
 * Validations (Flutter add_employee_widget.dart:649-781):
 *   1. Self-addition — cannot invite your own email.
 *   2. Duplicate employee — email already on the schedule's employees list.
 *   3. Email format — `functions.isEmailValid()`.
 *   4. Duplicate request — an ADD_RQUEST_PENDING invite already exists for
 *      this email on this schedule (the manager is offered a reminder/resend).
 *
 * Data writes go through `lib/requests.ts` (the existing, test-covered
 * `schedule_requests` data layer) — this module does NOT touch Firestore rules.
 */

import type { EmployeeDetails } from "./types";
import type { ScheduleRequest } from "./requests-types";
import {
  createScheduleRequest,
  getUserByEmail,
  triggerPushNotification,
  type InviteeUser,
} from "./requests";

/**
 * Email regex ported verbatim from Flutter's `isEmailValid`
 * (lib/flutter_flow/custom_functions.dart:258-265, the FlutterFlow
 * `kTextValidatorEmailRegex`). Kept identical so the web and Flutter accept
 * exactly the same set of addresses.
 */
const EMAIL_REGEX =
  /^(?:[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*|"(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21\x23-\x5b\x5d-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])*")@(?:(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\[(?:(?:(2(5[0-5]|[0-4][0-9])|1[0-9][0-9]|[1-9]?[0-9]))\.){3}(?:(2(5[0-5]|[0-4][0-9])|1[0-9][0-9]|[1-9]?[0-9])|[a-z0-9-]*[a-z0-9]:(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21-\x5a\x53-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])+)\])$/i;

export function isEmailValid(email: string): boolean {
  return EMAIL_REGEX.test(email.trim());
}

/**
 * Machine-readable failure reasons so the UI can map each to a localized
 * message (the copy itself lives in i18n-dict.ts, matching Flutter's
 * en/he/es snackbar strings).
 */
export type InviteErrorCode =
  | "self"
  | "duplicate_employee"
  | "invalid_email"
  | "duplicate_request"
  | "generic";

export class InviteError extends Error {
  code: InviteErrorCode;
  constructor(code: InviteErrorCode, message?: string) {
    super(message ?? code);
    this.name = "InviteError";
    this.code = code;
  }
}

export interface SendInviteInput {
  scheduleId: string;
  scheduleName: string;
  /** Email entered by the manager. */
  email: string;
  /** The manager's uid (becomes `from_user`). */
  fromUserUid: string;
  /** The manager's own email — for the self-addition guard. */
  fromUserEmail: string;
  /** Current employees on the schedule — for the duplicate guard. */
  employees: EmployeeDetails[];
  /** Existing pending add-requests on the schedule — for duplicate-request. */
  pendingRequests: ScheduleRequest[];
}

export interface SendInviteResult {
  /** New `schedule_requests` doc id. */
  requestId: string;
  /** True when the invitee already had an account (push was attempted). */
  invitedExistingUser: boolean;
}

/**
 * Localized push-notification copy — mirrors Flutter
 * add_employee_widget.dart:254-265. The web app currently only renders en;
 * we pick the string by the caller-provided locale so the recipient gets the
 * message in their inviter's UI language, matching the Flutter behavior of
 * resolving `FFLocalizations.of(context).getVariableText`.
 */
const PUSH_TITLE: Record<string, string> = {
  en: "Work Schedule Update",
  he: "עדכון בסידור עבודה",
  es: "Actualización del horario de trabajo",
};
const PUSH_BODY: Record<string, string> = {
  en: "You've been requested to be added a work schedule! Tap to view details.",
  he: "התבקשת להתווסף לסידור עבודה! הקש כדי להציג פרטים.",
  es: "¡Se le ha solicitado que se le agregue un horario de trabajo! Toque para ver los detalles.",
};

/**
 * Run the full Flutter invite flow for one email.
 *
 * Throws `InviteError` for each validation failure (self / duplicate employee
 * / invalid email / duplicate pending request) so the caller can show the
 * matching localized snackbar. On success writes a `schedule_requests` doc and
 * (best-effort) fires a push notification to an existing-account invitee.
 *
 * @param locale  active UI locale ("en" | "he" | "es") for the push copy.
 */
export async function sendEmployeeInvite(
  input: SendInviteInput,
  locale: string = "en"
): Promise<SendInviteResult> {
  const email = input.email.trim();

  // VALIDATION 1 — self-addition (add_employee_widget.dart:649-689).
  if (email.toLowerCase() === input.fromUserEmail.trim().toLowerCase()) {
    throw new InviteError("self");
  }

  // VALIDATION 2 — duplicate employee (add_employee_widget.dart:691-739).
  const alreadyEmployed = input.employees.some(
    (e) => (e.employee_email ?? "").toLowerCase() === email.toLowerCase()
  );
  if (alreadyEmployed) {
    throw new InviteError("duplicate_employee");
  }

  // VALIDATION 3 — email format (add_employee_widget.dart:741-781).
  if (!isEmailValid(email)) {
    throw new InviteError("invalid_email");
  }

  // VALIDATION 4 — duplicate pending invitation
  // (add_employee_widget.dart:940-1020 / 1336-1340). One pending add-request
  // per email per schedule. The manager should withdraw or wait rather than
  // create a second invite.
  const dupRequest = input.pendingRequests.some(
    (r) =>
      (r.to_user_identification ?? "").toLowerCase() === email.toLowerCase()
  );
  if (dupRequest) {
    throw new InviteError("duplicate_request");
  }

  // USER LOOKUP — resolve to_user if the invitee already has an account
  // (add_employee_widget.dart:790-804). Lookup failure is non-fatal: fall back
  // to an email-only invite (to_user: null), exactly like the new-user path.
  let invitee: InviteeUser | null = null;
  try {
    invitee = await getUserByEmail(email);
  } catch {
    invitee = null;
  }

  // CREATE the schedule_requests doc (add_employee_widget.dart:168-184).
  const requestId = await createScheduleRequest({
    isAddRequest: true,
    isJoinRequest: false,
    scheduleName: input.scheduleName,
    requestStatus: "ADD_RQUEST_PENDING",
    fromUserUid: input.fromUserUid,
    toUserUid: invitee?.uid ?? null,
    toUserIdentification: email,
    scheduleId: input.scheduleId,
  });

  // NOTIFY existing-account invitees only (add_employee_widget.dart:233-270).
  // Best-effort — never let a push failure surface or roll back the invite.
  if (invitee) {
    try {
      await triggerPushNotification({
        notificationTitle: PUSH_TITLE[locale] ?? PUSH_TITLE.en,
        notificationText: PUSH_BODY[locale] ?? PUSH_BODY.en,
        toUserUids: [invitee.uid],
        fromUserUid: input.fromUserUid,
        initialPageName: "Home",
        parameterData: { shouldDisplayScheduleRequest: true },
      });
    } catch {
      // swallow — invite already persisted
    }
  }

  return { requestId, invitedExistingUser: Boolean(invitee) };
}
