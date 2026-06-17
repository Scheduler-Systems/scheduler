import ScheduleDetailClient from "./schedule-detail-client";

// Returns a dummy param so static export builds; SPA rewrite handles real IDs at runtime.
export function generateStaticParams() {
  return [{ id: "_" }];
}

export default function ScheduleDetailPage() {
  return <ScheduleDetailClient />;
}
