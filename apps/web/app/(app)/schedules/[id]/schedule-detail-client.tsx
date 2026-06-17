"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getSchedule,
  getLatestBuiltSchedule,
  getAllPrioritySubmissions,
  getMonthlyBuildCount,
} from "@/lib/firestore";
import { BuiltScheduleGrid } from "@/components/built-schedule-grid";
import {
  updateScheduleName,
  addEmployee,
  removeEmployee,
  publishBuiltSchedule,
  deleteSchedule,
  incrementMonthlyBuildCount,
} from "@/lib/firestore-write";
import { useAuth } from "@/lib/auth-context";
import { useBilling } from "@/lib/billing/billing-context";
import {
  PaywallModal,
  type PaywallTrigger,
} from "@/components/paywall/paywall-modal";
import { startSeatBandCheckout } from "@/lib/billing/purchase";
import type { SeatBand } from "@/lib/billing/seat-bands";
import {
  buildSchedule,
  type PriorityMap,
  type ScheduleConflict,
} from "@/lib/schedule-builder";
import { parseEnabledShifts } from "@/lib/shifts";
import { builtScheduleToCsv, downloadCsv } from "@/lib/csv-export";
import { exportBuiltScheduleToPdf, getPdfFilename } from "@/lib/pdf-export";
import { useI18n } from "@/lib/i18n-context";
import { InviteEmployeeSection } from "@/components/employees/invite-employee-section";
import { ScheduleBuiltCelebration } from "@/components/schedule-built-celebration";
import type { Schedule, EmployeeDetails, RoleStruct } from "@/lib/types";

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function roleBadge(role: EmployeeDetails["role"]) {
  if (role?.is_creator) return "Creator";
  if (role?.is_admin) return "Admin";
  return "Worker";
}

function roleColor(role: EmployeeDetails["role"]) {
  // Flutter role accents: Manager (creator/admin) = primary purple,
  // Employee (worker) = pink #F551C9.
  if (role?.is_creator) return "bg-purple-100 text-purple-700";
  if (role?.is_admin) return "bg-purple-100 text-purple-700";
  return "bg-pink-100 text-pink-700";
}

const ROLES: { label: string; value: keyof RoleStruct }[] = [
  { label: "Worker", value: "is_worker" },
  { label: "Admin", value: "is_admin" },
  { label: "Creator", value: "is_creator" },
];

function makeRole(selected: keyof RoleStruct): RoleStruct {
  return {
    is_creator: selected === "is_creator",
    is_admin: selected === "is_admin" || selected === "is_creator",
    is_worker: true,
  };
}

export default function ScheduleDetailClient() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const { tier, limits } = useBilling();
  const { t } = useI18n();
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Paywall state — `paywallTrigger=null` means closed. One modal covers both
  // build-count and user-count limits; the trigger string picks the copy.
  const [paywallTrigger, setPaywallTrigger] = useState<PaywallTrigger | null>(null);
  const [paywallError, setPaywallError] = useState<string | null>(null);

  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const [editingName, setEditingName] = useState(false);
  const [nameValue, setNameValue] = useState("");
  const [savingName, setSavingName] = useState(false);

  const [showAddForm, setShowAddForm] = useState(false);
  const [empName, setEmpName] = useState("");
  const [empEmail, setEmpEmail] = useState("");
  const [empPhone, setEmpPhone] = useState("");
  const [empRole, setEmpRole] = useState<keyof RoleStruct>("is_worker");
  const [addingEmp, setAddingEmp] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const [removingIdx, setRemovingIdx] = useState<number | null>(null);

  const [building, setBuilding] = useState(false);
  const [buildMsg, setBuildMsg] = useState<string | null>(null);
  // Schedule-built confetti (Flutter parity). State guard: set true ONLY from
  // the publishBuiltSchedule() success path inside handleBuild — an event, not
  // derived from load/render state — so it cannot fire on mount, re-render,
  // hard reload, or navigation back to this page. The celebration auto-clears
  // it via onDone after the burst plays out (~2.6s).
  const [celebrateBuild, setCelebrateBuild] = useState(false);
  const [builtCounter, setBuiltCounter] = useState(0);
  const [showBuildForm, setShowBuildForm] = useState(false);
  const [buildStart, setBuildStart] = useState<string>(() => {
    const d = new Date();
    d.setUTCHours(0, 0, 0, 0);
    const daysUntilSunday = (7 - d.getUTCDay()) % 7 || 7;
    d.setUTCDate(d.getUTCDate() + daysUntilSunday);
    return d.toISOString().slice(0, 10);
  });
  const [buildDays, setBuildDays] = useState<number>(7);
  const [avoidConflicts, setAvoidConflicts] = useState(true);
  const [lastConflicts, setLastConflicts] = useState<ScheduleConflict[]>([]);
  const [exporting, setExporting] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const s = await getSchedule(id);
      if (!s) setError("Schedule not found.");
      else {
        setSchedule(s);
        setNameValue(s.schedule_name ?? "");
      }
    } catch {
      setError("Failed to load schedule.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // Wire the paywall's seat-band selection to the RevenueCat HOSTED checkout.
  // Previously this call site rendered the modal with NO onSelectBand, so the
  // "Continue" button was a dead no-op — a user who hit the build-count or
  // user-count gate could never actually purchase. startSeatBandCheckout never
  // throws — it resolves to success / error and redirects the tab to the band's
  // the hosted-checkout page (the real charge happens there). RevenueCat keys the
  // customer by Firebase uid (matches the Flutter app + read-back), not email.
  async function handleSelectBand(band: SeatBand) {
    if (!user) return;
    setPaywallError(null);
    const result = await startSeatBandCheckout(band, user.uid);
    if (result.status === "success") {
      setPaywallTrigger(null);
      // Redirect already issued by startSeatBandCheckout; nothing more to do.
    } else if (result.status === "error") {
      setPaywallError(result.message ?? "Purchase could not be completed.");
    }
  }

  async function handleSaveName() {
    if (!schedule || !nameValue.trim()) return;
    setSavingName(true);
    try {
      const uids = (schedule.employees ?? [])
        .map((e) => e.user_ref?.id)
        .filter(Boolean) as string[];
      await updateScheduleName(schedule.id, nameValue.trim(), uids);
      setSchedule({ ...schedule, schedule_name: nameValue.trim() });
      setEditingName(false);
    } catch {
      // Keep editing open so user can retry
    } finally {
      setSavingName(false);
    }
  }

  async function handleAddEmployee(e: React.FormEvent) {
    e.preventDefault();
    if (!schedule || !empName.trim()) {
      setAddError("Employee name is required.");
      return;
    }
    // P1-4 user-limit gate — the owner + existing employees count against
    // `limits.maxUsers`. At the cap we open the paywall instead of writing.
    const currentEmployees = schedule.employees ?? [];
    if (currentEmployees.length >= limits.maxUsers) {
      setPaywallTrigger("user");
      return;
    }
    setAddingEmp(true);
    setAddError(null);
    const newEmp: Omit<EmployeeDetails, "user_ref"> = {
      employee_name: empName.trim(),
      employee_email: empEmail.trim(),
      employee_phone: empPhone.trim(),
      role: makeRole(empRole),
    };
    try {
      await addEmployee(schedule.id, newEmp);
      await load();
      setEmpName(""); setEmpEmail(""); setEmpPhone("");
      setEmpRole("is_worker");
      setShowAddForm(false);
    } catch {
      setAddError("Failed to add employee. Please try again.");
    } finally {
      setAddingEmp(false);
    }
  }

  async function handleBuild() {
    if (!schedule) return;
    // P1-4 build-count gate — only enforced on the free tier. Paid tiers
    // have `maxBuildsPerMonth = Infinity` so the compare short-circuits. We
    // read the count on every build attempt (not cached in state) so a
    // stale window after an upgrade doesn't hold the user back.
    if (tier === "free" && user?.uid) {
      try {
        const used = await getMonthlyBuildCount(user.uid);
        if (used >= limits.maxBuildsPerMonth) {
          setPaywallTrigger("build");
          return;
        }
      } catch {
        // Billing read failed — let the build proceed rather than
        // blocking a legit user on a Firestore hiccup.
      }
    }
    setBuilding(true);
    setBuildMsg(null);
    try {
      const shifts = parseEnabledShifts(schedule.schedule_settings?.enabled_shifts);
      if (shifts.length === 0) {
        setBuildMsg("Enable at least one shift in Settings before building.");
        return;
      }
      const days = Math.max(1, Math.min(31, Math.floor(buildDays) || 7));
      const startIso = buildStart || new Date().toISOString().slice(0, 10);
      const start = new Date(`${startIso}T00:00:00Z`);
      if (isNaN(start.getTime())) {
        setBuildMsg("Invalid start date.");
        return;
      }
      const workers = (schedule.employees ?? []).map((e) => ({
        name: e.employee_name || "",
      }));
      const numStations = schedule.schedule_settings?.num_of_stations ?? 1;

      const end = new Date(start);
      end.setUTCDate(end.getUTCDate() + (days - 1));

      // Load submitted priorities to bias the builder (falls back to fairness
      // when no submissions exist for a worker).
      const subs = await getAllPrioritySubmissions(schedule.id);
      const priorities: PriorityMap = {};
      for (const sub of subs) {
        if (!sub.display_name) continue;
        priorities[sub.display_name] = new Set(sub.priorities);
      }

      const built = buildSchedule({
        employees: workers,
        enabledShifts: shifts,
        numDays: days,
        numStations,
        startDate: start,
        avoidSameDayConflicts: avoidConflicts,
        priorities,
      });
      setLastConflicts(built.conflicts);

      await publishBuiltSchedule(schedule.id, {
        rows: built.rows,
        firstWeekday: built.firstWeekday,
        lastWeekday: built.lastWeekday,
        startDate: start,
        endDate: end,
        currentPriorities: schedule.current_priorities ?? [],
      });
      // Bump the per-user monthly counter — used by the P1-4 free-tier gate.
      // Best-effort: a failed write here must not surface to the user (the
      // build already published). Worst case is one extra free build later.
      if (user?.uid) {
        await incrementMonthlyBuildCount(user.uid).catch(() => undefined);
      }
      setBuildMsg("Published new schedule.");
      setBuiltCounter((c) => c + 1);
      setShowBuildForm(false);
      // Fire the confetti once per successful build — non-blocking overlay
      // (pointer-events-none), auto-dismisses, never re-fires on re-render.
      setCelebrateBuild(true);
    } catch {
      setBuildMsg("Failed to build schedule. Please try again.");
    } finally {
      setBuilding(false);
    }
  }

  async function handleExportCsv() {
    if (!schedule) return;
    setExporting(true);
    try {
      const built = await getLatestBuiltSchedule(schedule.id);
      if (!built) return;
      const shifts = parseEnabledShifts(
        schedule.schedule_settings?.enabled_shifts
      );
      const numShifts = Math.max(shifts.length, 1);
      const numDays = Math.ceil((built.schedule?.length ?? 0) / numShifts);
      const days: string[] = [];
      const startTs = built.first_weekday_datetime;
      const startDate = startTs
        ? // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (startTs as any).toDate?.() ?? null
        : null;
      for (let d = 0; d < numDays; d++) {
        if (startDate instanceof Date) {
          const day = new Date(startDate);
          day.setDate(startDate.getDate() + d);
          days.push(day.toISOString().slice(0, 10));
        } else {
          days.push(DAY_LABELS[d % 7] + ` #${d + 1}`);
        }
      }
      const csv = builtScheduleToCsv(built, { days, shifts });
      const safeName = (schedule.schedule_name || "schedule").replace(
        /[^a-zA-Z0-9-_]/g,
        "_"
      );
      downloadCsv(`${safeName}.csv`, csv);
    } finally {
      setExporting(false);
    }
  }

  async function handleDownloadPdf() {
    if (!schedule) return;
    setExportingPdf(true);
    try {
      const built = await getLatestBuiltSchedule(schedule.id);
      if (!built) return;
      const blob = await exportBuiltScheduleToPdf(schedule, built);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = getPdfFilename(schedule);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } finally {
      setExportingPdf(false);
    }
  }

  async function handleRemove(emp: EmployeeDetails, idx: number) {
    if (!schedule) return;
    setRemovingIdx(idx);
    try {
      await removeEmployee(schedule.id, emp);
      await load();
    } catch {
      // silently ignore — UI stays consistent after reload
    } finally {
      setRemovingIdx(null);
    }
  }

  async function handleDelete() {
    if (!schedule) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      // Best-effort: include the current user's uid in the involved list so
      // their own schedules_involved back-reference is cleaned up. Other
      // members' back-references can only be cleaned if we have their uids,
      // which we don't store on the schedule — they're orphaned pointers
      // that will 404 on read.
      const involvedUids = user?.uid ? [user.uid] : [];
      await deleteSchedule(schedule.id, involvedUids);
      router.replace("/schedules");
    } catch {
      setDeleteError("Failed to delete. Please try again.");
      setDeleting(false);
    }
  }

  // Only creator can delete. Admins can manage employees but not nuke the
  // schedule.
  const currentUserRole = schedule?.employees?.find(
    (e) => e.employee_email?.toLowerCase() === user?.email?.toLowerCase()
  )?.role;
  const canDelete = currentUserRole?.is_creator === true;
  // Manager = creator OR admin — matches Flutter's add-employee gate.
  const canManageEmployees =
    currentUserRole?.is_creator === true || currentUserRole?.is_admin === true;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-6 h-6 border-2 border-purple-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error || !schedule) {
    return (
      <div className="space-y-4">
        <Link href="/schedules" className="text-sm text-purple-600 hover:underline">
          ← Back to Schedules
        </Link>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error ?? "Schedule not found."}
        </div>
      </div>
    );
  }

  const employees = schedule.employees ?? [];
  const settings = schedule.schedule_settings;

  return (
    <div className="space-y-6">
      <Link href="/schedules" className="text-sm text-purple-600 hover:underline">
        ← Schedules
      </Link>

      <div>
        {editingName ? (
          <div className="flex items-center gap-2">
            <input
              autoFocus
              value={nameValue}
              onChange={(e) => setNameValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSaveName();
                if (e.key === "Escape") {
                  setEditingName(false);
                  setNameValue(schedule.schedule_name ?? "");
                }
              }}
              className="flex-1 max-w-sm rounded-lg border border-gray-300 px-3 py-1.5 text-xl font-semibold focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
            <button
              onClick={handleSaveName}
              disabled={savingName}
              className="rounded-lg bg-purple-600 px-3 py-1.5 text-sm text-white hover:bg-purple-700 disabled:opacity-50"
            >
              {savingName ? "Saving…" : "Save"}
            </button>
            <button
              onClick={() => {
                setEditingName(false);
                setNameValue(schedule.schedule_name ?? "");
              }}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold">
              {schedule.schedule_name || "Unnamed Schedule"}
            </h1>
            <button
              onClick={() => setEditingName(true)}
              className="text-gray-400 hover:text-gray-600"
              title="Edit name"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
              </svg>
            </button>
            <div className="ml-auto flex items-center gap-2">
              <Link
                href={`/schedules/${schedule.id}/requests`}
                className="rounded-lg border border-gray-200 px-3 py-1 text-sm text-gray-600 hover:bg-gray-50"
              >
                Requests
              </Link>
              <Link
                href={`/schedules/${schedule.id}/priorities`}
                className="rounded-lg border border-gray-200 px-3 py-1 text-sm text-gray-600 hover:bg-gray-50"
              >
                Priorities
              </Link>
              <Link
                href={`/schedules/${schedule.id}/archived`}
                className="rounded-lg border border-gray-200 px-3 py-1 text-sm text-gray-600 hover:bg-gray-50"
              >
                Archive
              </Link>
              <Link
                href={`/schedules/${schedule.id}/settings`}
                className="rounded-lg border border-gray-200 px-3 py-1 text-sm text-gray-600 hover:bg-gray-50"
              >
                Settings
              </Link>
            </div>
          </div>
        )}
        {settings && (
          <p className="text-sm text-gray-500 mt-1">
            {settings.num_of_stations > 0
              ? `${settings.num_of_stations} station${settings.num_of_stations !== 1 ? "s" : ""}`
              : ""}
            {parseEnabledShifts(settings.enabled_shifts).length
              ? ` · ${parseEnabledShifts(settings.enabled_shifts).join(", ")}`
              : ""}
          </p>
        )}
      </div>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-medium">Employees ({employees.length})</h2>
          <div className="flex items-center gap-2">
            <Link
              href={`/schedules/${schedule.id}/import`}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm hover:bg-gray-50 transition-colors"
            >
              Import CSV
            </Link>
            <button
              onClick={() => setShowAddForm((v) => !v)}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm hover:bg-gray-50 transition-colors"
            >
              {showAddForm ? "Cancel" : "+ Add employee"}
            </button>
          </div>
        </div>

        {showAddForm && (
          <form
            onSubmit={handleAddEmployee}
            className="mb-4 rounded-lg border border-purple-200 bg-purple-50 p-4 space-y-3"
          >
            <p className="text-sm font-medium text-purple-800">New employee</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <input
                type="text"
                placeholder="Full name *"
                value={empName}
                onChange={(e) => setEmpName(e.target.value)}
                className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
              <input
                type="email"
                placeholder="Email"
                value={empEmail}
                onChange={(e) => setEmpEmail(e.target.value)}
                className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
              <input
                type="tel"
                placeholder="Phone"
                value={empPhone}
                onChange={(e) => setEmpPhone(e.target.value)}
                className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
              <select
                value={empRole}
                onChange={(e) => setEmpRole(e.target.value as keyof RoleStruct)}
                className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              >
                {ROLES.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>
            {addError && <p className="text-xs text-red-600">{addError}</p>}
            <button
              type="submit"
              disabled={addingEmp}
              className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            >
              {addingEmp ? "Adding…" : "Add employee"}
            </button>
          </form>
        )}

        {employees.length === 0 ? (
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-6 text-center text-sm text-gray-500">
            No employees yet. Use the button above to add the first one.
          </div>
        ) : (
          <div className="rounded-lg border border-gray-200 overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Name</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Role</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide hidden sm:table-cell">Email</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide hidden md:table-cell">Phone</th>
                  <th className="px-4 py-3 w-10" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {employees.map((emp, idx) => (
                  <tr key={idx} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{emp.employee_name || "—"}</td>
                    <td className="px-4 py-3 text-sm">
                      <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${roleColor(emp.role)}`}>
                        {roleBadge(emp.role)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 hidden sm:table-cell">{emp.employee_email || "—"}</td>
                    <td className="px-4 py-3 text-sm text-gray-500 hidden md:table-cell">{emp.employee_phone || "—"}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => handleRemove(emp, idx)}
                        disabled={removingIdx === idx}
                        className="text-gray-300 hover:text-red-500 disabled:opacity-40 transition-colors"
                        title="Remove"
                      >
                        {removingIdx === idx ? (
                          <span className="text-xs">…</span>
                        ) : (
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        )}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Employee invite/accept loop (B4) — gated to the INTERNAL audience
            via scheduler.web-employee-invite; renders null for customers. */}
        {schedule ? (
          <InviteEmployeeSection
            scheduleId={schedule.id}
            scheduleName={schedule.schedule_name ?? ""}
            employees={employees}
            canManage={canManageEmployees}
          />
        ) : null}
      </section>

      <section>
        <div className="flex items-center justify-between mb-3 gap-3">
          <h2 className="text-lg font-medium">Published Schedule</h2>
          <div className="flex items-center gap-2">
            {buildMsg && (
              <span className="text-sm text-gray-600">{buildMsg}</span>
            )}
            <button
              onClick={handleExportCsv}
              disabled={exporting}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
            >
              {exporting ? "Exporting…" : "Export CSV"}
            </button>
            <button
              onClick={handleDownloadPdf}
              disabled={exportingPdf}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
            >
              {exportingPdf ? "Exporting…" : t("scheduleDetail.downloadPdf")}
            </button>
            <button
              onClick={() => setShowBuildForm((v) => !v)}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm hover:bg-gray-50"
            >
              {showBuildForm ? "Cancel" : "+ Build schedule"}
            </button>
          </div>
        </div>

        {showBuildForm && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleBuild();
            }}
            className="mb-4 rounded-lg border border-purple-200 bg-purple-50 p-4 space-y-3"
          >
            <p className="text-sm font-medium text-purple-800">Build options</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="space-y-1 text-sm">
                <span className="text-gray-700">Start date</span>
                <input
                  type="date"
                  value={buildStart}
                  onChange={(e) => setBuildStart(e.target.value)}
                  className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="text-gray-700">Duration (days)</span>
                <input
                  type="number"
                  min={1}
                  max={31}
                  value={buildDays}
                  onChange={(e) =>
                    setBuildDays(parseInt(e.target.value, 10) || 7)
                  }
                  className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
                />
              </label>
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={avoidConflicts}
                onChange={(e) => setAvoidConflicts(e.target.checked)}
              />
              Avoid assigning the same worker to two shifts on one day
            </label>
            <p className="text-xs text-gray-500">
              Submitted priorities are honored first; the rest is filled by
              fairness-weighted round-robin.
            </p>
            <button
              type="submit"
              disabled={building}
              className="rounded-lg bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            >
              {building ? "Building…" : "Publish"}
            </button>
          </form>
        )}

        {lastConflicts.length > 0 && (
          <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            <p className="font-medium mb-1">
              {lastConflicts.length} same-day conflict
              {lastConflicts.length === 1 ? "" : "s"} in the last build:
            </p>
            <ul className="list-disc list-inside text-xs space-y-0.5">
              {lastConflicts.slice(0, 10).map((c, i) => (
                <li key={i}>
                  Day {c.dayIndex + 1}: {c.worker} is on {c.shifts.join(" + ")}
                </li>
              ))}
              {lastConflicts.length > 10 && (
                <li className="text-gray-500">
                  …and {lastConflicts.length - 10} more
                </li>
              )}
            </ul>
          </div>
        )}

        <BuiltScheduleGrid key={builtCounter} schedule={schedule} />
      </section>

      {paywallError && (
        <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {paywallError}
        </div>
      )}

      <PaywallModal
        open={paywallTrigger !== null}
        onClose={() => {
          setPaywallTrigger(null);
          setPaywallError(null);
        }}
        onSelectBand={handleSelectBand}
        trigger={paywallTrigger ?? "build"}
      />

      {canDelete && (
        <section className="rounded-lg border border-red-200 bg-red-50 p-4">
          <h2 className="text-sm font-semibold text-red-700">Danger zone</h2>
          <p className="text-xs text-red-600 mt-1">
            Deleting this schedule removes it along with all built schedules,
            priority submissions, and member back-references. This cannot be
            undone.
          </p>
          {deleteError && (
            <p className="mt-2 text-xs text-red-700 font-medium">
              {deleteError}
            </p>
          )}
          <div className="mt-3 flex items-center gap-2">
            {!deleteConfirm ? (
              <button
                type="button"
                onClick={() => setDeleteConfirm(true)}
                className="rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100"
              >
                Delete schedule…
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleting}
                  className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                >
                  {deleting
                    ? "Deleting…"
                    : `Yes, delete "${schedule.schedule_name}"`}
                </button>
                <button
                  type="button"
                  onClick={() => setDeleteConfirm(false)}
                  disabled={deleting}
                  className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
              </>
            )}
          </div>
        </section>
      )}

      {/* Schedule-built confetti — Flutter parity (ConfettiAnimationWidget
          machinery + the "Congrats! Your new schedule is ready." beat).
          Fires once from the build-success path in handleBuild. */}
      <ScheduleBuiltCelebration
        show={celebrateBuild}
        onDone={() => setCelebrateBuild(false)}
      />
    </div>
  );
}
