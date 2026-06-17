"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { useBilling } from "@/lib/billing/billing-context";
import {
  createSchedule,
  updateScheduleSettings,
  ScheduleNameTakenError,
} from "@/lib/firestore-write";
import { getUserSchedules } from "@/lib/firestore";
import { PaywallModal } from "@/components/paywall/paywall-modal";
import { startSeatBandCheckout } from "@/lib/billing/purchase";
import type { SeatBand } from "@/lib/billing/seat-bands";

// Only the three canonical FlutterFlow shift slots — matches
// EnabledShiftsStruct.morning/afternoon/night. Custom labels aren't
// rendered by the Flutter builder, so we keep the web-side honest and
// let Settings expose hour-string tweaks instead.
type CanonicalShift = "morning" | "afternoon" | "night";

const CANONICAL_SHIFTS: { key: CanonicalShift; label: string }[] = [
  { key: "morning", label: "Morning" },
  { key: "afternoon", label: "Afternoon" },
  { key: "night", label: "Night" },
];

export default function NewSchedulePage() {
  const router = useRouter();
  const { user } = useAuth();
  const { limits } = useBilling();

  const [name, setName] = useState("");
  const [stations, setStations] = useState(1);
  const [enabled, setEnabled] = useState<Set<CanonicalShift>>(
    new Set(["morning", "afternoon"])
  );
  const [morningHours, setMorningHours] = useState("");
  const [noonHours, setNoonHours] = useState("");
  const [nightHours, setNightHours] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPaywall, setShowPaywall] = useState(false);
  const [purchaseError, setPurchaseError] = useState<string | null>(null);

  // Wire the paywall's seat-band selection to the RevenueCat HOSTED checkout.
  // Previously this call site rendered the modal with NO onSelectBand, so the
  // "Continue" button was a dead no-op and a user who hit the station gate
  // could never actually purchase. startSeatBandCheckout never throws — it
  // resolves to success / error and redirects the tab to the band's
  // the hosted-checkout page (the real charge happens there). RevenueCat keys the
  // customer by Firebase uid (matches the Flutter app + read-back), not email.
  async function handleSelectBand(band: SeatBand) {
    if (!user) return;
    setPurchaseError(null);
    const result = await startSeatBandCheckout(band, user.uid);
    if (result.status === "success") {
      setShowPaywall(false);
      // Redirect already issued by startSeatBandCheckout; nothing more to do.
    } else if (result.status === "error") {
      setPurchaseError(result.message ?? "Purchase could not be completed.");
    }
  }

  function toggleShift(key: CanonicalShift) {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!user) return;
    if (!name.trim()) {
      setError("Schedule name is required.");
      return;
    }
    if (enabled.size === 0) {
      setError("Enable at least one shift.");
      return;
    }
    // Fetch existing schedules once and apply both checks against the same
    // snapshot — avoids a double read and keeps enforcement consistent.
    //
    // Check 1: duplicate name (case-insensitive) — block before writing.
    // Check 2: P1-4 station-count gate — at the cap, route to paywall.
    //
    // If the read fails we fall through on both checks; the Flutter app uses
    // the same "favor availability over strict enforcement" pattern when
    // Firestore is transiently flaky.
    try {
      const existing = await getUserSchedules(user.uid);

      // Duplicate name check — case-insensitive so "Clinic" and "clinic"
      // are treated as the same schedule.
      const trimmedName = name.trim().toLowerCase();
      const nameTaken = existing.some(
        (s) => s.schedule_name?.toLowerCase() === trimmedName
      );
      if (nameTaken) {
        setError(
          "A schedule with this name already exists. Please choose a different name."
        );
        return;
      }

      // Station-count paywall gate.
      if (existing.length >= limits.maxStations) {
        setShowPaywall(true);
        return;
      }
    } catch {
      // Non-fatal — proceed if the read fails; Firestore is the source of
      // truth and the create will fail there if there is a real conflict.
    }
    setSaving(true);
    setError(null);
    try {
      const id = await createSchedule({
        scheduleName: name.trim(),
        numOfStations: stations,
        enabledShifts: Array.from(enabled),
        ownerUid: user.uid,
        ownerEmail: user.email ?? "",
        ownerName: user.displayName ?? user.email ?? "",
      });
      // If any hours were filled, write them via the settings update so the
      // doc ends up with the canonical EnabledShiftsStruct shape including
      // *_hours strings. Skipped when all blank to avoid a second write.
      const anyHours =
        morningHours.trim() || noonHours.trim() || nightHours.trim();
      if (anyHours) {
        await updateScheduleSettings(id, {
          enabled_shifts: Array.from(enabled),
          num_of_stations: stations,
          morning_hours: morningHours.trim(),
          noon_hours: noonHours.trim(),
          night_hours: nightHours.trim(),
        });
      }
      router.push(`/schedules/${id}`);
    } catch (e) {
      // The transactional uniqueness check can still reject a duplicate that
      // slipped past the pre-check (e.g. a concurrent create) — surface the
      // same clear message rather than a generic failure.
      if (e instanceof ScheduleNameTakenError) {
        setError(
          "A schedule with this name already exists. Please choose a different name."
        );
      } else {
        setError("Failed to create schedule. Please try again.");
      }
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6 max-w-lg">
      <div className="flex items-center gap-2">
        <Link href="/schedules" className="text-sm text-purple-600 hover:underline">
          ← Schedules
        </Link>
      </div>

      <div>
        <h1 className="text-2xl font-semibold">New Schedule</h1>
        <p className="text-sm text-gray-500 mt-1">Set up a new shift schedule</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Schedule name <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Weekly Clinic Rota"
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Number of stations
          </label>
          <input
            type="number"
            min={1}
            max={50}
            value={stations}
            onChange={(e) => setStations(Math.max(1, Number(e.target.value)))}
            className="w-24 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Enabled shifts
          </label>
          <div className="flex flex-wrap gap-2">
            {CANONICAL_SHIFTS.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                onClick={() => toggleShift(key)}
                className={`rounded-full px-3 py-1 text-sm border transition-colors ${
                  enabled.has(key)
                    ? "bg-purple-600 text-white border-purple-600"
                    : "bg-white text-gray-600 border-gray-200 hover:border-purple-300"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-gray-400">
            These three slots match what the Flutter app renders. You can
            still tweak hour ranges below.
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Shift hours <span className="text-gray-400 font-normal">(optional)</span>
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <label className="space-y-1 text-xs">
              <span className="text-gray-600">Morning</span>
              <input
                type="text"
                value={morningHours}
                onChange={(e) => setMorningHours(e.target.value)}
                disabled={!enabled.has("morning")}
                placeholder="06:00–14:00"
                className="w-full rounded-lg border border-gray-200 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:opacity-50"
              />
            </label>
            <label className="space-y-1 text-xs">
              <span className="text-gray-600">Noon / afternoon</span>
              <input
                type="text"
                value={noonHours}
                onChange={(e) => setNoonHours(e.target.value)}
                disabled={!enabled.has("afternoon")}
                placeholder="14:00–22:00"
                className="w-full rounded-lg border border-gray-200 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:opacity-50"
              />
            </label>
            <label className="space-y-1 text-xs">
              <span className="text-gray-600">Night</span>
              <input
                type="text"
                value={nightHours}
                onChange={(e) => setNightHours(e.target.value)}
                disabled={!enabled.has("night")}
                placeholder="22:00–06:00"
                className="w-full rounded-lg border border-gray-200 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:opacity-50"
              />
            </label>
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="flex gap-3 pt-2">
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? "Creating…" : "Create schedule"}
          </button>
          <Link
            href="/schedules"
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            Cancel
          </Link>
        </div>
      </form>

      {purchaseError && (
        <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {purchaseError}
        </div>
      )}

      <PaywallModal
        open={showPaywall}
        onClose={() => setShowPaywall(false)}
        onSelectBand={handleSelectBand}
        trigger="station"
      />
    </div>
  );
}
