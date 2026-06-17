"use client";

// P3-3 — manager-side request detail + approve/reject.
//
// Loads a single `scheduleChangeRequest` doc and offers the two
// resolution buttons. Approve writes `status: 'accepted'` and sets
// `resolved_at: serverTimestamp()` — this is the trigger shape our
// Cloud Functions watch to fan out FCM notifications. Reject writes
// `status: 'rejected'` (mapped to Flutter's `'declined'` on read).

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n-context";
import { getSchedule } from "@/lib/firestore";
import {
  getScheduleChangeRequest,
  updateScheduleChangeRequestStatus,
} from "@/lib/requests";
import type { Schedule } from "@/lib/types";
import type { ScheduleChangeRequest } from "@/lib/requests-types";

function formatTimestamp(ts: ScheduleChangeRequest["DateTime"]): string {
  if (!ts) return "";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const d = (ts as any).toDate?.();
  if (d instanceof Date) {
    return d.toISOString().slice(0, 16).replace("T", " ");
  }
  return "";
}

function splitReason(reason: string): { target?: string; body: string } {
  const match = reason.match(/^Swap with (.+?):\s*/);
  if (match) {
    return { target: match[1], body: reason.slice(match[0].length) };
  }
  return { body: reason };
}

function requesterNameFor(
  schedule: Schedule | null,
  userId: string | undefined
): string {
  if (!userId) return "";
  for (const emp of schedule?.employees ?? []) {
    const uid = (emp.user_ref as { id?: string } | null)?.id;
    if (uid && uid === userId) return emp.employee_name || emp.employee_email;
  }
  return userId;
}

export default function RequestDetailClient() {
  const { id, requestId } = useParams<{ id: string; requestId: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const { t } = useI18n();

  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [request, setRequest] = useState<ScheduleChangeRequest | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pending, setPending] = useState<"approve" | "reject" | null>(null);

  const load = useCallback(async () => {
    if (!id || !requestId) return;
    try {
      const [s, r] = await Promise.all([
        getSchedule(id),
        getScheduleChangeRequest(requestId),
      ]);
      setSchedule(s);
      setRequest(r);
      if (!r) setLoadError(t("requests.notFound"));
    } catch {
      setLoadError(t("requests.errorLoad"));
    } finally {
      setLoading(false);
    }
  }, [id, requestId, t]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleAction(kind: "approve" | "reject") {
    if (!request || !user || !requestId) return;
    setPending(kind);
    setActionError(null);
    try {
      // Approve maps to Flutter's `accepted`; reject maps to `rejected`.
      // We deliberately use `rejected` (not Flutter's `declined`) because
      // the web UI surfaces it cleanly and the inbox list tolerates both
      // strings as the "resolved" state.
      const status = kind === "approve" ? "accepted" : "rejected";
      await updateScheduleChangeRequestStatus(requestId, status, user.uid);
      router.push(`/schedules/${id}/requests`);
    } catch {
      setActionError(t("requests.actionErrorGeneric"));
      setPending(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (loadError || !request) {
    return (
      <div className="space-y-4">
        <Link
          href={`/schedules/${id}/requests`}
          className="text-sm text-purple-600 hover:underline"
        >
          {t("requests.backToInbox")}
        </Link>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {loadError ?? t("requests.notFound")}
        </div>
      </div>
    );
  }

  const parsed = splitReason(request.Reason ?? "");
  const isPending =
    request.status === "sent" || request.status === "pending";
  const requesterName = requesterNameFor(schedule, request.userId);

  const statusLabel =
    request.status === "accepted"
      ? t("requests.statusApproved")
      : request.status === "declined" || request.status === "rejected"
        ? t("requests.statusRejected")
        : t("requests.statusPending");

  const statusColor =
    request.status === "accepted"
      ? "bg-green-100 text-green-700"
      : request.status === "declined" || request.status === "rejected"
        ? "bg-red-100 text-red-700"
        : "bg-amber-100 text-amber-700";

  return (
    <div className="space-y-6 max-w-lg">
      <Link
        href={`/schedules/${id}/requests`}
        className="text-sm text-purple-600 hover:underline"
      >
        {t("requests.backToInbox")}
      </Link>

      <div className="flex items-start justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t("requests.detailTitle")}</h1>
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${statusColor}`}
        >
          {statusLabel}
        </span>
      </div>

      <dl className="rounded-lg border border-gray-200 bg-white divide-y divide-gray-200">
        <div className="px-4 py-3">
          <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">
            {t("requests.detailRequester")}
          </dt>
          <dd className="mt-1 text-sm text-gray-900">{requesterName}</dd>
        </div>
        {parsed.target && (
          <div className="px-4 py-3">
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">
              {t("requests.detailTarget")}
            </dt>
            <dd className="mt-1 text-sm text-gray-900">{parsed.target}</dd>
          </div>
        )}
        <div className="px-4 py-3">
          <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">
            {t("requests.detailShift")}
          </dt>
          <dd className="mt-1 text-sm text-gray-900">
            {formatTimestamp(request.DateTime)}
          </dd>
        </div>
        <div className="px-4 py-3">
          <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">
            {t("requests.detailReason")}
          </dt>
          <dd className="mt-1 text-sm text-gray-900 whitespace-pre-wrap">
            {parsed.body || "—"}
          </dd>
        </div>
      </dl>

      {actionError && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {actionError}
        </div>
      )}

      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => handleAction("approve")}
          disabled={!isPending || pending !== null}
          className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {pending === "approve"
            ? t("requests.approving")
            : t("requests.approve")}
        </button>
        <button
          type="button"
          onClick={() => handleAction("reject")}
          disabled={!isPending || pending !== null}
          className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {pending === "reject"
            ? t("requests.rejecting")
            : t("requests.reject")}
        </button>
      </div>
    </div>
  );
}
