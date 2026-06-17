"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { getUserSchedules } from "@/lib/firestore";
import { useI18n } from "@/lib/i18n-context";
import type { EmployeeDetails, Schedule } from "@/lib/types";

interface EmployeeRow extends EmployeeDetails {
  scheduleId: string;
  scheduleName: string;
}

export default function EmployeesPage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const [employees, setEmployees] = useState<EmployeeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  function roleBadge(role: EmployeeDetails["role"]) {
    if (role?.is_creator) return t("employees.roleCreator");
    if (role?.is_admin) return t("employees.roleAdmin");
    return t("employees.roleWorker");
  }

  useEffect(() => {
    if (!user) return;
    getUserSchedules(user.uid)
      .then((schedules: Schedule[]) => {
        const rows: EmployeeRow[] = [];
        for (const s of schedules) {
          for (const emp of s.employees ?? []) {
            rows.push({
              ...emp,
              scheduleId: s.id,
              scheduleName: s.schedule_name,
            });
          }
        }
        // Deduplicate by employee_email+scheduleId (same employee can be in multiple schedules)
        const seen = new Set<string>();
        const deduped = rows.filter((r) => {
          const key = `${r.employee_email}::${r.scheduleId}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
        setEmployees(deduped);
      })
      .catch(() => setError(t("employees.errorLoad")))
      .finally(() => setLoading(false));
  }, [user, t]);

  const filtered = search.trim()
    ? employees.filter(
        (e) =>
          e.employee_name?.toLowerCase().includes(search.toLowerCase()) ||
          e.employee_email?.toLowerCase().includes(search.toLowerCase())
      )
    : employees;

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
      <div>
        <h1 className="text-2xl font-semibold">{t("employees.heading")}</h1>
        <p className="text-sm text-gray-500 mt-1">
          {t("employees.subheading")}
        </p>
      </div>

      {employees.length > 0 && (
        <input
          type="search"
          placeholder={t("employees.searchPlaceholder")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full max-w-sm rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
        />
      )}

      {filtered.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-8 text-center">
          <p className="text-gray-500">
            {search ? t("employees.emptyNoMatch") : t("employees.emptyMessage")}
          </p>
          {!search &&
            (() => {
              const hint = t("employees.emptyHint");
              const [before, after = ""] = hint.split("{scheduleLink}");
              return (
                <p className="text-sm text-gray-400 mt-1">
                  {before}
                  <Link href="/schedules" className="text-purple-600 hover:underline">
                    {t("employees.emptyHintLink")}
                  </Link>
                  {after}
                </p>
              );
            })()}
        </div>
      ) : (
        <div className="rounded-lg border border-gray-200 overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  {t("employees.tableName")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide hidden sm:table-cell">
                  {t("employees.tableEmail")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide hidden md:table-cell">
                  {t("employees.tablePhone")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  {t("employees.tableSchedule")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide hidden sm:table-cell">
                  {t("employees.tableRole")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {filtered.map((emp, idx) => (
                <tr key={idx} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">
                    {emp.employee_name || "—"}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500 hidden sm:table-cell">
                    {emp.employee_email || "—"}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500 hidden md:table-cell">
                    {emp.employee_phone || "—"}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    <Link
                      href={`/schedules/${emp.scheduleId}`}
                      className="hover:text-purple-600 hover:underline"
                    >
                      {emp.scheduleName || "—"}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-sm hidden sm:table-cell">
                    <span className="text-xs text-gray-500">
                      {roleBadge(emp.role)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
