"use client";

// Reusable days × shifts grid.
// `assignments[`${day}|${shift}`] = string[]` maps cells to assigned names.
// Reused by Phase 6 (ScheduleSettings) and Phase 7 (schedule builder).
export interface ShiftGridProps {
  days: string[];
  shifts: string[];
  assignments?: Record<string, string[]>;
  onCellClick?: (cell: { day: string; shift: string }) => void;
  readOnly?: boolean;
}

const shiftLabel = (s: string) =>
  s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");

export function ShiftGrid({
  days,
  shifts,
  assignments,
  onCellClick,
  readOnly,
}: ShiftGridProps) {
  if (days.length === 0 || shifts.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
        No shifts configured.
      </div>
    );
  }

  const interactive = !readOnly && typeof onCellClick === "function";

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-white px-3 py-2 text-left font-medium text-gray-500" />
            {days.map((day) => (
              <th
                key={day}
                className="min-w-[90px] border-b border-gray-200 px-3 py-2 text-center font-medium text-gray-700"
              >
                {day}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shifts.map((shift) => (
            <tr key={shift}>
              <th
                scope="row"
                className="sticky left-0 z-10 bg-white border-r border-gray-200 px-3 py-2 text-left font-medium text-gray-600"
              >
                {shiftLabel(shift)}
              </th>
              {days.map((day) => {
                const key = `${day}|${shift}`;
                const names = assignments?.[key] ?? [];
                const testId = `cell-${day}-${shift}`;
                const classes = [
                  "border-b border-r border-gray-100 px-2 py-2 align-top text-left",
                  interactive
                    ? "cursor-pointer hover:bg-purple-50"
                    : "cursor-default",
                ].join(" ");
                const content =
                  names.length === 0 ? (
                    <span className="text-xs text-gray-300">—</span>
                  ) : (
                    <ul className="space-y-0.5">
                      {names.map((n) => (
                        <li
                          key={n}
                          className="truncate rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700"
                        >
                          {n}
                        </li>
                      ))}
                    </ul>
                  );
                return (
                  <td
                    key={key}
                    data-testid={testId}
                    className={classes}
                    onClick={
                      interactive
                        ? () => onCellClick?.({ day, shift })
                        : undefined
                    }
                  >
                    {content}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
