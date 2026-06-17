"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { getDashboardSummary, type DashboardSummary } from "@/lib/firestore";
import { useI18n } from "@/lib/i18n-context";
import { AppBar } from "@/components/app-bar";

export default function DashboardPage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) return;
    getDashboardSummary(user.uid)
      .then(setSummary)
      .catch(() => setSummary(null))
      .finally(() => setLoading(false));
  }, [user]);

  return (
    <div>
      {/* Foundation F4 reference usage: the shared purple AppBar primitive.
          Other screens are retrofitted in a later per-screen pass. */}
      <AppBar title={t("dashboard.heading")} />

      <div className="space-y-6 p-4">
        <p className="text-sm text-[var(--color-secondary-text)]">
          {t("dashboard.subheading")}
        </p>

      {/* Stat cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <p className="text-sm text-gray-500">{t("dashboard.statSchedules")}</p>
          <p className="text-3xl font-semibold mt-1">
            {loading ? <span className="text-gray-200">—</span> : (summary?.scheduleCount ?? 0)}
          </p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <p className="text-sm text-gray-500">{t("dashboard.statEmployees")}</p>
          <p className="text-3xl font-semibold mt-1">
            {loading ? <span className="text-gray-200">—</span> : (summary?.employeeCount ?? 0)}
          </p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-5 col-span-2 sm:col-span-1">
          <p className="text-sm text-gray-500">{t("dashboard.quickActions")}</p>
          <div className="mt-2 space-y-1">
            <Link href="/schedules/new" className="block text-sm text-purple-600 hover:underline">
              {t("dashboard.newSchedule")}
            </Link>
            <Link href="/schedules" className="block text-sm text-purple-600 hover:underline">
              {t("dashboard.viewAllSchedules")}
            </Link>
          </div>
        </div>
      </div>

      {/* Schedules list */}
      {!loading && summary && summary.schedules.length > 0 && (
        <div>
          <h2 className="text-lg font-medium mb-3">{t("dashboard.schedulesListHeading")}</h2>
          <div className="rounded-lg border border-gray-200 overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">{t("dashboard.tableSchedule")}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">{t("dashboard.tableEmployees")}</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {summary.schedules.map((s) => (
                  <tr key={s.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">
                      {s.name || t("dashboard.unnamedSchedule")}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">{s.employeeCount}</td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/schedules/${s.id}`}
                        className="text-sm text-purple-600 hover:underline"
                      >
                        {t("dashboard.openSchedule")}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && summary && summary.schedules.length === 0 && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-8 text-center">
          <p className="text-gray-500">{t("dashboard.emptyMessage")}</p>
          <Link href="/schedules/new" className="mt-2 inline-block text-sm text-purple-600 hover:underline">
            {t("dashboard.emptyCta")}
          </Link>
        </div>
      )}
      </div>
    </div>
  );
}
