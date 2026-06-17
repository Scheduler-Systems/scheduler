"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { getUserSchedules } from "@/lib/firestore";
import { parseEnabledShifts } from "@/lib/shifts";
import { useI18n } from "@/lib/i18n-context";
import type { Schedule } from "@/lib/types";

export default function SchedulesPage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    getUserSchedules(user.uid)
      .then(setSchedules)
      .catch(() => setError(t("schedulesList.errorLoad")))
      .finally(() => setLoading(false));
  }, [user, t]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{t("schedulesList.heading")}</h1>
          <p className="text-sm text-gray-500 mt-1">
            {t("schedulesList.subheading")}
          </p>
        </div>
        <Link
          href="/schedules/new"
          className="rounded-lg bg-purple-600 px-3 py-2 text-sm font-medium text-white hover:bg-purple-700 transition-colors"
        >
          {t("schedulesList.newSchedule")}
        </Link>
      </div>

      {schedules.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-8 text-center">
          <p className="text-gray-500">{t("schedulesList.emptyMessage")}</p>
          <p className="text-sm text-gray-400 mt-1">
            {t("schedulesList.emptyHint")}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {schedules.map((s) => {
            const employeeCount = s.employees?.length ?? 0;
            const shiftCount = parseEnabledShifts(
              s.schedule_settings?.enabled_shifts,
            ).length;
            return (
              <Link
                key={s.id}
                href={`/schedules/${s.id}`}
                className="block rounded-lg border border-gray-200 bg-white p-5 hover:border-purple-300 hover:shadow-sm transition-all"
              >
                <p className="font-medium truncate">
                  {s.schedule_name || t("schedulesList.unnamedSchedule")}
                </p>
                <p className="text-sm text-gray-500 mt-1">
                  {t(
                    employeeCount === 1
                      ? "schedulesList.employeeCountOne"
                      : "schedulesList.employeeCountOther",
                    { count: employeeCount }
                  )}
                </p>
                {shiftCount > 0 ? (
                  <p className="text-xs text-gray-400 mt-1">
                    {t(
                      shiftCount === 1
                        ? "schedulesList.shiftCountOne"
                        : "schedulesList.shiftCountOther",
                      { count: shiftCount }
                    )}
                  </p>
                ) : null}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
