// CSV export for a BuiltSchedule. Kept dependency-free so the bundle stays
// small — we'd otherwise pull in jsPDF + autotable just to render a grid that
// every spreadsheet tool already handles. Downloads use a Blob URL on click.

import type { BuiltSchedule } from "./types";

export function escapeCsvField(value: string): string {
  if (/[",\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

export interface CsvExportOptions {
  days: string[];
  shifts: string[];
}

export function builtScheduleToCsv(
  built: BuiltSchedule,
  opts: CsvExportOptions,
): string {
  const lines: string[] = ["Day,Shift,Assigned"];
  const rows = built.schedule ?? [];
  const numShifts = Math.max(opts.shifts.length, 1);
  for (let d = 0; d < opts.days.length; d++) {
    for (let s = 0; s < opts.shifts.length; s++) {
      const row = rows[d * numShifts + s];
      const names = (row?.stringList ?? []).filter(Boolean).join(" & ");
      lines.push(
        [
          escapeCsvField(opts.days[d]),
          escapeCsvField(opts.shifts[s]),
          escapeCsvField(names),
        ].join(","),
      );
    }
  }
  return lines.join("\n");
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
