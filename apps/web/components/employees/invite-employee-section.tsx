"use client";

/**
 * Employee invite section — the web port of Flutter's employee-management
 * invite UI. Mounts inside a schedule's employee view; gated behind the
 * INTERNAL Pilotlight flag `scheduler.web-employee-invite` so it ships DARK to
 * paying customers and is visible only to Scheduler-Systems staff during the
 * parity pilot (mirrors scheduler.agent-workforce — see
 * .tmp/sched-web-round1/PATTERN-internal-tier-flag-gating.md).
 *
 * Flutter sources of truth (cited inline):
 *   - lib/production_pages/add_employee/add_employee_widget.dart
 *       · purple AppBar (primary #6A0DAD)        — line 323-324
 *       · title "Add Employee"                    — line 348
 *       · "Add employee with" heading             — line 410
 *       · Email label + field                     — line 431, 530-542
 *       · send → schedule_requests (is_add_request) — invite orchestration
 *   - lib/production_pages/employee_list/employee_list_widget.dart
 *       · two-tab "Employees List" / "Add requests" TabBar — line 66-239
 *       · pending add-request card                — line 223-240, 331-347
 *       · withdraw (delete) add request           — line 568-570
 *
 * Data path: the existing Firestore-direct helpers (lib/employee-invite.ts +
 * lib/requests.ts). The Go-API cutover is a separate track — this matches the
 * current direct-write paradigm.
 */

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n-context";
import {
  useFeatureFlag,
  WEB_EMPLOYEE_INVITE_FLAG,
} from "@/lib/feature-flags/use-feature-flag";
import {
  sendEmployeeInvite,
  InviteError,
  type InviteErrorCode,
} from "@/lib/employee-invite";
import {
  getPendingAddRequestsForSchedule,
  deleteScheduleRequest,
} from "@/lib/requests";
import type { ScheduleRequest } from "@/lib/requests-types";
import type { EmployeeDetails } from "@/lib/types";

// Brand purple — Flutter FlutterFlowTheme.primary (#6A0DAD). Used for the
// AppBar/heading and the pending-request card accent (#9643D1 in Flutter's
// employee_details_tile; we use the schedule-detail purple family already in
// the web app).
const PRIMARY = "#6A0DAD";

interface InviteEmployeeSectionProps {
  scheduleId: string;
  scheduleName: string;
  /** Current employees on the schedule — for the duplicate-employee guard. */
  employees: EmployeeDetails[];
  /** Whether the signed-in user may manage (creator/admin). When false the
   *  invite controls are hidden, matching Flutter's manager-only gate. */
  canManage?: boolean;
}

const INVITE_ERROR_KEY: Record<InviteErrorCode, string> = {
  self: "invite.errorSelf",
  duplicate_employee: "invite.errorDuplicateEmployee",
  invalid_email: "invite.errorInvalidEmail",
  duplicate_request: "invite.errorDuplicateRequest",
  generic: "invite.errorGeneric",
};

type Tab = "employees" | "requests";

export function InviteEmployeeSection(props: InviteEmployeeSectionProps) {
  const enabled = useFeatureFlag(WEB_EMPLOYEE_INVITE_FLAG);
  // Customers ALWAYS get false (resolved synchronously) → the module never
  // flashes for them. Internal staff get the Pilotlight value.
  if (!enabled) return null;
  return <InviteEmployeeSectionInner {...props} />;
}

function InviteEmployeeSectionInner({
  scheduleId,
  scheduleName,
  employees,
  canManage = true,
}: InviteEmployeeSectionProps) {
  const { user } = useAuth();
  const { t, locale } = useI18n();

  const [tab, setTab] = useState<Tab>("employees");
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [pending, setPending] = useState<ScheduleRequest[]>([]);
  const [withdrawingId, setWithdrawingId] = useState<string | null>(null);

  const loadPending = useCallback(async () => {
    try {
      const reqs = await getPendingAddRequestsForSchedule(scheduleId);
      setPending(reqs);
    } catch {
      // non-fatal — pending list just stays empty
    }
  }, [scheduleId]);

  useEffect(() => {
    void loadPending();
  }, [loadPending]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!user || sending) return;
    setError(null);
    setSuccess(null);
    setSending(true);
    try {
      const result = await sendEmployeeInvite(
        {
          scheduleId,
          scheduleName,
          email,
          fromUserUid: user.uid,
          fromUserEmail: user.email ?? "",
          employees,
          pendingRequests: pending,
        },
        locale
      );
      setSuccess(
        result.invitedExistingUser
          ? t("invite.sentBodyExisting")
          : t("invite.sentBodyEmail", { email: email.trim() })
      );
      setEmail("");
      await loadPending();
      setTab("requests");
    } catch (err) {
      const code =
        err instanceof InviteError ? err.code : ("generic" as InviteErrorCode);
      setError(t(INVITE_ERROR_KEY[code]));
    } finally {
      setSending(false);
    }
  }

  async function handleWithdraw(id: string) {
    if (withdrawingId) return;
    if (!window.confirm(t("invite.withdrawConfirm"))) return;
    setWithdrawingId(id);
    setError(null);
    try {
      await deleteScheduleRequest(id);
      setPending((prev) => prev.filter((r) => r.id !== id));
    } catch {
      setError(t("invite.withdrawError"));
    } finally {
      setWithdrawingId(null);
    }
  }

  return (
    <section className="mt-6 overflow-hidden rounded-[10px] border border-[#E5E5E5] bg-white">
      {/* Purple AppBar — Flutter add_employee_widget.dart:323-348 (primary). */}
      <div
        className="flex items-center px-4 py-3 text-white"
        style={{ backgroundColor: PRIMARY }}
      >
        <h2 className="text-base font-semibold font-[var(--font-montserrat)]">
          {t("invite.addEmployee")}
        </h2>
      </div>

      {/* Two-tab bar — Flutter employee_list_widget.dart:66-239
          (List / Add-requests). */}
      <div className="flex border-b border-[#E5E5E5]" role="tablist">
        <TabButton
          active={tab === "employees"}
          onClick={() => setTab("employees")}
          label={t("invite.tabEmployees")}
        />
        <TabButton
          active={tab === "requests"}
          onClick={() => setTab("requests")}
          label={
            pending.length > 0
              ? t("invite.tabRequestsCount", { count: String(pending.length) })
              : t("invite.tabRequests")
          }
        />
      </div>

      {tab === "employees" ? (
        canManage ? (
          <form onSubmit={handleSend} className="space-y-3 p-4">
            {/* "Add employee with" — Flutter add_employee_widget.dart:410. */}
            <p className="text-sm font-semibold" style={{ color: PRIMARY }}>
              {t("invite.addEmployeeWith")}
            </p>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-[#57636C]">
                {t("invite.emailLabel")}
              </span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t("invite.emailPlaceholder")}
                required
                disabled={sending}
                className="w-full rounded-lg border border-[#E5E5E5] px-3 py-2 text-sm outline-none focus:border-[#6A0DAD] focus:ring-1 focus:ring-[#6A0DAD]"
                dir="ltr"
              />
            </label>

            {error ? (
              <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            ) : null}
            {success ? (
              <p className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
                {success}
              </p>
            ) : null}

            {/* Send button — Flutter FFButton (primary, height 50, radius 8). */}
            <button
              type="submit"
              disabled={sending || email.trim().length === 0}
              className="h-[50px] w-full rounded-lg text-sm font-semibold text-white shadow-sm transition disabled:opacity-50"
              style={{ backgroundColor: PRIMARY }}
            >
              {sending ? t("invite.sending") : t("invite.sendInvite")}
            </button>
          </form>
        ) : (
          <p className="p-4 text-sm text-[#57636C]">{t("invite.pendingEmpty")}</p>
        )
      ) : (
        <PendingRequestsList
          pending={pending}
          withdrawingId={withdrawingId}
          canManage={canManage}
          onWithdraw={handleWithdraw}
          t={t}
        />
      )}
    </section>
  );
}

function TabButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`flex-1 px-4 py-3 text-sm font-medium transition ${
        active
          ? "border-b-2 text-[#6A0DAD]"
          : "border-b-2 border-transparent text-[#57636C] hover:text-[#6A0DAD]"
      }`}
      style={active ? { borderColor: PRIMARY } : undefined}
    >
      {label}
    </button>
  );
}

function PendingRequestsList({
  pending,
  withdrawingId,
  canManage,
  onWithdraw,
  t,
}: {
  pending: ScheduleRequest[];
  withdrawingId: string | null;
  canManage: boolean;
  onWithdraw: (id: string) => void;
  t: (key: string, params?: Record<string, string>) => string;
}) {
  if (pending.length === 0) {
    return (
      <p className="p-4 text-sm text-[#57636C]">{t("invite.pendingEmpty")}</p>
    );
  }
  return (
    <ul className="divide-y divide-[#E5E5E5]">
      {pending.map((r) => (
        <li
          key={r.id}
          className="flex items-center justify-between gap-3 px-4 py-3"
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-[#14181B]" dir="ltr">
              {r.to_user_identification}
            </p>
            <p className="text-xs text-[#57636C]">
              {t("invite.invitedLabel")} · {t("invite.pendingStatus")}
            </p>
          </div>
          {canManage ? (
            <button
              type="button"
              onClick={() => onWithdraw(r.id)}
              disabled={withdrawingId === r.id}
              className="shrink-0 rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-700 transition hover:bg-red-50 disabled:opacity-50"
            >
              {withdrawingId === r.id
                ? t("invite.withdrawing")
                : t("invite.withdraw")}
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
