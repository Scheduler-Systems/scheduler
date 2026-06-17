"use client";

// P3-3 — manager-side request inbox list.
//
// Lists every schedule-change request for a given schedule. Tabs for
// "Pending" vs "Resolved" (anything other than the `sent` status is
// considered resolved). Rows navigate to the detail page.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useI18n } from "@/lib/i18n-context";
import {
  getScheduleChangeRequestsForSchedule,
} from "@/lib/requests";
import { getSchedule } from "@/lib/firestore";
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

// Map an employee uid / email to a display name via the schedule's
// employees list. Returns the uid/email itself as a fallback so the UI
// still shows something sensible.
function employeeNameLookup(schedule: Schedule | null) {
  const byKey = new Map<string, string>();
  for (const emp of schedule?.employees ?? []) {
    const uid = (emp.user_ref as { id?: string } | null)?.id;
    const name = emp.employee_name || emp.employee_email || "";
    if (uid) byKey.set(uid, name);
    if (emp.employee_email) byKey.set(emp.employee_email.toLowerCase(), name);
  }
  return (key: string | undefined | null): string => {
    if (!key) return "";
    return byKey.get(key) ?? byKey.get(key.toLowerCase()) ?? key;
  };
}

// Very simple extractor for the "swap with X" string we embed in the
// Reason when a request is submitted via the web UI. Optional — if the
// record came from Flutter or doesn't contain the marker, we just
// return the raw reason.
function splitReason(reason: string): { target?: string; body: string } {
  const match = reason.match(/^Swap with (.+?):\s*/);
  if (match) {
    return { target: match[1], body: reason.slice(match[0].length) };
  }
  return { body: reason };
}

type Tab = "pending" | "resolved";

export default function RequestsInboxClient() {
  const { id } = useParams<{ id: string }>();
  const { t } = useI18n();

  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [requests, setRequests] = useState<ScheduleChangeRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("pending");

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [s, rs] = await Promise.all([
        getSchedule(id),
        getScheduleChangeRequestsForSchedule(id),
      ]);
      setSchedule(s);
      setRequests(rs);
    } catch {
      setLoadError(t("requests.errorLoad"));
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    load();
  }, [load]);

  const nameOf = useMemo(() => employeeNameLookup(schedule), [schedule]);

  const { pending, resolved } = useMemo(() => {
    const p: ScheduleChangeRequest[] = [];
    const r: ScheduleChangeRequest[] = [];
    for (const req of requests) {
      if (req.status === "sent" || req.status === "pending") p.push(req);
      else r.push(req);
    }
    return { pending: p, resolved: r };
  }, [requests]);

  const rows = tab === "pending" ? pending : resolved;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Link
        href={`/schedules/${id}`}
        className="text-sm text-purple-600 hover:underline"
      >
        ← {schedule?.schedule_name ?? t("nav.schedules")}
      </Link>

      <div className="flex items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t("requests.pageTitle")}</h1>
        <Link
          href={`/schedules/${id}/requests/new`}
          className="rounded-lg bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700"
        >
          {t("requests.newRequestLink")}
        </Link>
      </div>

      <div
        role="tablist"
        aria-label={t("requests.pageTitle")}
        className="border-b border-gray-200"
      >
        <button
          role="tab"
          aria-selected={tab === "pending"}
          onClick={() => setTab("pending")}
          className={`inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "pending"
              ? "border-purple-600 text-purple-600"
              : "border-transparent text-gray-500 hover:text-gray-900"
          }`}
        >
          {t("requests.tabPending")}
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
            {pending.length}
          </span>
        </button>
        <button
          role="tab"
          aria-selected={tab === "resolved"}
          onClick={() => setTab("resolved")}
          className={`inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "resolved"
              ? "border-purple-600 text-purple-600"
              : "border-transparent text-gray-500 hover:text-gray-900"
          }`}
        >
          {t("requests.tabResolved")}
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
            {resolved.length}
          </span>
        </button>
      </div>

      {loadError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {loadError}
        </div>
      )}

      {rows.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-6 text-center text-sm text-gray-500">
          {t("requests.emptyMessage")}
        </div>
      ) : (
        <ul className="divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white">
          {rows.map((req) => {
            const parsed = splitReason(req.Reason ?? "");
            const requesterName = nameOf(req.userId);
            const statusLabel =
              req.status === "accepted"
                ? t("requests.statusApproved")
                : req.status === "declined" || req.status === "rejected"
                  ? t("requests.statusRejected")
                  : t("requests.statusPending");
            const statusColor =
              req.status === "accepted"
                ? "bg-green-100 text-green-700"
                : req.status === "declined" || req.status === "rejected"
                  ? "bg-red-100 text-red-700"
                  : "bg-amber-100 text-amber-700";
            return (
              <li key={req.id}>
                <Link
                  href={`/schedules/${id}/requests/${req.id}`}
                  className="block px-4 py-3 hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">
                        {requesterName || req.userId}
                        {parsed.target ? (
                          <>
                            <span className="text-gray-400"> → </span>
                            <span className="text-gray-700">
                              {parsed.target}
                            </span>
                          </>
                        ) : null}
                      </p>
                      <p className="text-xs text-gray-500 truncate mt-0.5">
                        {formatTimestamp(req.DateTime)}
                      </p>
                    </div>
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${statusColor}`}
                    >
                      {statusLabel}
                    </span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
