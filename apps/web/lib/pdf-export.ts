// PDF export for a BuiltSchedule. Mirrors the row-shape of csv-export.ts but
// renders a printable table with a title, date range, auto-table body, and a
// page-number + generation-timestamp footer on each page.
//
// jspdf + jspdf-autotable are dynamically imported inside
// `exportBuiltScheduleToPdf` so they stay off the initial bundle. Only the
// schedule-detail route pays the ~250KB cost, and only after a user clicks
// "Download PDF".

import type { BuiltSchedule, Schedule } from "./types";
import { parseEnabledShifts } from "./shifts";

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

interface PdfRow {
  shift: string;
  day: string;
  employee: string;
  start: string;
  end: string;
  priority: string;
}

// Deterministic ordinal->label for days: use first_weekday_datetime when we
// have one, else fall back to DAY_LABELS + ordinal.
function formatDay(
  dayIndex: number,
  startDate: Date | null,
): string {
  if (startDate instanceof Date && !isNaN(startDate.getTime())) {
    const d = new Date(startDate);
    d.setUTCDate(startDate.getUTCDate() + dayIndex);
    return d.toISOString().slice(0, 10);
  }
  return `${DAY_LABELS[dayIndex % 7]} #${dayIndex + 1}`;
}

// Build the tabular rows that the PDF renders. Kept as a plain function so
// tests can exercise it without a PDF backend. Not exported publicly — the
// shape is an implementation detail, but the header row is contractually
// fixed (see tests).
function buildPdfRows(
  schedule: Schedule,
  built: BuiltSchedule,
): PdfRow[] {
  const shifts = parseEnabledShifts(schedule.schedule_settings?.enabled_shifts);
  const numShifts = Math.max(shifts.length, 1);
  const rows = built.schedule ?? [];
  const numDays = Math.ceil(rows.length / numShifts);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rawStart = (built.first_weekday_datetime as any)?.toDate?.() ?? null;
  const startDate = rawStart instanceof Date ? rawStart : null;

  const priorities = schedule.current_priorities ?? [];
  const settings = schedule.schedule_settings;

  const hoursFor = (shift: string): { start: string; end: string } => {
    if (shift === "morning") return parseHours(settings?.morning_hours);
    if (shift === "afternoon" || shift === "noon")
      return parseHours(settings?.noon_hours);
    if (shift === "night") return parseHours(settings?.night_hours);
    return { start: "", end: "" };
  };

  const out: PdfRow[] = [];
  for (let d = 0; d < numDays; d++) {
    for (let s = 0; s < numShifts; s++) {
      const row = rows[d * numShifts + s];
      const names = (row?.stringList ?? []).filter(Boolean);
      const shift = shifts[s] ?? "";
      const { start, end } = hoursFor(shift);
      const dayLabel = formatDay(d, startDate);
      // One PDF row per assigned worker so the table reads like a roster.
      if (names.length === 0) {
        out.push({
          shift,
          day: dayLabel,
          employee: "",
          start,
          end,
          priority: priorities[d * numShifts + s] ?? "",
        });
      } else {
        for (const name of names) {
          out.push({
            shift,
            day: dayLabel,
            employee: name,
            start,
            end,
            priority: priorities[d * numShifts + s] ?? "",
          });
        }
      }
    }
  }
  return out;
}

// Hours strings are stored as "HH:MM-HH:MM" in the schedule settings.
// Flutter writes them that way via the shift-config UI; tolerate blanks.
function parseHours(raw: string | undefined): { start: string; end: string } {
  if (!raw) return { start: "", end: "" };
  const [start = "", end = ""] = raw.split(/[-–]/).map((s) => s.trim());
  return { start, end };
}

function formatDateRange(built: BuiltSchedule): string {
  const first = built.first_weekday?.trim() || "";
  const last = built.last_weekday?.trim() || "";
  if (first && last) return `${first} — ${last}`;
  return first || last;
}

// Title + date-range header row. Exported for callers that want the exact
// string we embed in the PDF (e.g. email subject lines).
export function getPdfTitle(schedule: Schedule, built: BuiltSchedule): string {
  const name = schedule.schedule_name?.trim() || "Untitled";
  const range = formatDateRange(built);
  return range ? `${name} Schedule · ${range}` : `${name} Schedule`;
}

// Filename helper — sanitizes unsafe filesystem characters so the download
// lands cleanly across browsers.
export function getPdfFilename(schedule: Schedule): string {
  const base = (schedule.schedule_name || "schedule").trim() || "schedule";
  const safe = base.replace(/[^a-zA-Z0-9-_]+/g, "_").replace(/^_+|_+$/g, "");
  const finalBase = safe || "schedule";
  return `${finalBase}.pdf`;
}

export async function exportBuiltScheduleToPdf(
  schedule: Schedule,
  built: BuiltSchedule,
): Promise<Blob> {
  // Lazy-load jspdf + autotable so they stay out of the initial bundle.
  // Only the schedules/[id] route — and only after a click — pays the cost.
  const [{ default: JsPDF }, { default: autoTable }] = await Promise.all([
    import("jspdf"),
    import("jspdf-autotable"),
  ]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const doc: any = new (JsPDF as any)({
    orientation: "portrait",
    unit: "pt",
    format: "a4",
  });

  // --- Title block --------------------------------------------------------
  doc.setFontSize(16);
  doc.text(getPdfTitle(schedule, built), 40, 50);

  // --- Body table ---------------------------------------------------------
  const rows = buildPdfRows(schedule, built);
  const body = rows.map((r) => [
    r.shift,
    r.day,
    r.employee,
    r.start,
    r.end,
    r.priority,
  ]);

  autoTable(doc, {
    startY: 80,
    head: [["Shift", "Day", "Employee", "Start", "End", "Priority"]],
    body,
    styles: { fontSize: 9 },
    headStyles: { fillColor: [168, 85, 247], textColor: 255 }, // purple-500
    theme: "striped",
    margin: { left: 40, right: 40 },
  });

  // --- Footer on each page: "Page N of M"  +  "Generated YYYY-MM-DD ..." --
  const pageCount: number = doc.getNumberOfPages();
  const pageHeight: number = doc.internal.pageSize.getHeight();
  const pageWidth: number = doc.internal.pageSize.getWidth();
  const generatedAt = new Date().toISOString();
  for (let i = 1; i <= pageCount; i++) {
    doc.setPage(i);
    doc.setFontSize(8);
    doc.text(`Page ${i} of ${pageCount}`, pageWidth - 80, pageHeight - 20);
    doc.text(`Generated ${generatedAt}`, 40, pageHeight - 20);
  }

  // Force application/pdf MIME so `URL.createObjectURL` triggers a proper
  // download instead of rendering inline in some browsers.
  const raw = doc.output("blob");
  if (raw instanceof Blob && raw.type === "application/pdf") return raw;
  return new Blob([raw], { type: "application/pdf" });
}
