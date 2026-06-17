"use client";

/**
 * Invitee accept/decline screen — the web port of Flutter's
 * `schedule_request_widget.dart`. An invited employee sees the schedule
 * invitations sent to them and chooses Approve or Decline.
 *
 * Gated behind the INTERNAL Pilotlight flag `scheduler.web-employee-invite`
 * (same flag as the manager invite section) so it ships DARK to paying
 * customers and is visible only to Scheduler-Systems staff during the pilot.
 *
 * Flutter source of truth — lib/production_pages/schedule_request/schedule_request_widget.dart:
 *   · loading state w/ SchedulerLoadingWidget + "Loading request details..."  — line 104-128
 *   · title "Schedule joining request" (displaySmall, 32px top / 24px bottom)  — line 148-154
 *   · "{name} has requested to add you to their work schedule."                — line 264
 *   · review hint "Please review the details above and choose to accept ..."   — line 704-709
 *   · Approve FFButton → ADD_REQUEST_ACCEPTED (primary, h50, white, elev2, r8)  — line 887-905, 1190+
 *   · Decline FFButton → ADD_REQUEST_DECLINED (kept in DB for dup-prevention)   — line 1571-1601
 *
 * Data path: existing Firestore-direct helpers (lib/requests.ts) —
 * getPendingInvitesForUser + updateScheduleRequestStatus.
 */

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n-context";
import {
  useFeatureFlag,
  WEB_EMPLOYEE_INVITE_FLAG,
} from "@/lib/feature-flags/use-feature-flag";
import {
  acceptScheduleInvite,
  getPendingInvitesForUser,
  updateScheduleRequestStatus,
} from "@/lib/requests";
import type { ScheduleRequest } from "@/lib/requests-types";

const PRIMARY = "#6A0DAD";

export default function InvitesPage() {
  const enabled = useFeatureFlag(WEB_EMPLOYEE_INVITE_FLAG);
  // Customers ALWAYS get false (synchronous) → the route renders nothing for
  // them. Internal staff get the Pilotlight value.
  if (!enabled) return null;
  return <InvitesPageInner />;
}

function InvitesPageInner() {
  const { user } = useAuth();
  const { t } = useI18n();

  const [invites, setInvites] = useState<ScheduleRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [actingId, setActingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const reqs = await getPendingInvitesForUser(user.uid);
      setInvites(reqs);
    } catch {
      setError(t("invite.errorGeneric"));
    } finally {
      setLoading(false);
    }
  }, [user, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(req: ScheduleRequest, accept: boolean) {
    if (!user || actingId) return;
    setActingId(req.id);
    setError(null);
    setNotice(null);
    try {
      if (accept) {
        // Approve = the FULL Flutter 4-write batch (status + schedules_involved
        // + schedule employees[] + schedule chat membership). Status alone is
        // not membership — schedule_request_widget.dart ~880-1010.
        await acceptScheduleInvite(req, {
          uid: user.uid,
          displayName: user.displayName ?? user.email?.split("@")[0] ?? "",
          email: user.email ?? "",
          phone: user.phoneNumber ?? "",
        });
      } else {
        // Decline → status only. Flutter keeps a declined request in the DB
        // (SMR-186 dup-prevention), so we update status rather than delete.
        await updateScheduleRequestStatus(
          req.id,
          "ADD_REQUEST_DECLINED",
          user.uid
        );
      }
      setInvites((prev) => prev.filter((r) => r.id !== req.id));
      setNotice(
        accept ? t("invite.requestAccepted") : t("invite.requestRejected")
      );
    } catch {
      setError(t("invite.errorGeneric"));
    } finally {
      setActingId(null);
    }
  }

  if (loading) {
    // Flutter loading state — schedule_request_widget.dart:104-128.
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <div
          className="h-10 w-10 animate-spin rounded-full border-[3px] border-t-transparent"
          style={{ borderColor: PRIMARY, borderTopColor: "transparent" }}
        />
        <p className="mt-4 text-sm text-[#57636C]">
          {t("invite.requestLoading")}
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl px-4 pb-4">
      {/* Title — Flutter schedule_request_widget.dart:148-154 (displaySmall). */}
      <h1
        className="pb-6 pt-8 text-2xl font-bold font-[var(--font-montserrat)]"
        style={{ color: PRIMARY }}
      >
        {t("invite.requestTitle")}
      </h1>

      {notice ? (
        <p className="mb-4 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      ) : null}

      {invites.length === 0 ? (
        // Flutter no-pending fallback (check_declined_schedule_request flow).
        <div className="rounded-[10px] border border-[#E5E5E5] bg-[#F5F5F5] p-6 text-center">
          <p className="text-base font-semibold text-[#14181B]">
            {t("invite.requestNoneTitle")}
          </p>
          <p className="mt-1 text-sm text-[#57636C]">
            {t("invite.requestNoneBody")}
          </p>
        </div>
      ) : (
        <ul className="space-y-4">
          {invites.map((req) => (
            <InviteCard
              key={req.id}
              req={req}
              acting={actingId === req.id}
              onApprove={() => act(req, true)}
              onDecline={() => act(req, false)}
              t={t}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function InviteCard({
  req,
  acting,
  onApprove,
  onDecline,
  t,
}: {
  req: ScheduleRequest;
  acting: boolean;
  onApprove: () => void;
  onDecline: () => void;
  t: (key: string, params?: Record<string, string>) => string;
}) {
  // Flutter renders "<inviter name> has requested to add you...". When we don't
  // have the inviter's display name we fall back to the schedule name as the
  // subject of the sentence, which still reads correctly.
  const inviterName = req.schedule_name || t("invite.scheduleLabel");

  return (
    <li className="rounded-[10px] border border-[#E5E5E5] bg-[#F5F5F5] p-4">
      <p className="text-sm text-[#14181B]">
        {t("invite.requestFrom", { name: inviterName })}
      </p>

      {/* Schedule label row. */}
      <div className="mt-3 rounded-lg bg-white p-3">
        <p className="text-xs font-medium uppercase text-[#57636C]">
          {t("invite.scheduleLabel")}
        </p>
        <p className="mt-0.5 text-sm font-semibold" style={{ color: PRIMARY }}>
          {req.schedule_name}
        </p>
      </div>

      {/* Review hint — schedule_request_widget.dart:704-709. */}
      <p className="mt-3 text-xs text-[#57636C]">{t("invite.requestReview")}</p>

      {/* Approve / Decline — Flutter FFButtons (height 50, radius 8). */}
      <div className="mt-4 space-y-2.5">
        <button
          type="button"
          onClick={onApprove}
          disabled={acting}
          className="h-[50px] w-full rounded-lg text-sm font-semibold text-white shadow-sm transition disabled:opacity-50"
          style={{ backgroundColor: PRIMARY }}
        >
          {acting ? t("invite.processing") : t("invite.approve")}
        </button>
        <button
          type="button"
          onClick={onDecline}
          disabled={acting}
          className="h-[50px] w-full rounded-lg border bg-white text-sm font-semibold transition disabled:opacity-50"
          style={{ borderColor: PRIMARY, color: PRIMARY }}
        >
          {acting ? t("invite.processing") : t("invite.decline")}
        </button>
      </div>
    </li>
  );
}
