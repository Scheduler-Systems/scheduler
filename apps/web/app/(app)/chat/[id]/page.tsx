import ChatThreadClient from "./chat-thread-client";

// Dummy param satisfies static export; SPA rewrite handles real IDs at runtime.
// Matches the pattern used for schedules/[id]/page.tsx.
export function generateStaticParams() {
  return [{ id: "_" }];
}

export default function ChatThreadPage() {
  return <ChatThreadClient />;
}
