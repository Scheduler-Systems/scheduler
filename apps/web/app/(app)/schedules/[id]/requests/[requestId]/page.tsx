import RequestDetailClient from "./request-detail-client";

// Dummy params satisfy static export; SPA rewrite resolves real IDs
// at runtime. Both dynamic segments must appear here or the build fails.
export function generateStaticParams() {
  return [{ id: "_", requestId: "_" }];
}

export default function RequestDetailPage() {
  return <RequestDetailClient />;
}
