import NewRequestClient from "./new-request-client";

// Dummy param satisfies static export; SPA rewrite handles real IDs at runtime.
export function generateStaticParams() {
  return [{ id: "_" }];
}

export default function NewRequestPage() {
  return <NewRequestClient />;
}
