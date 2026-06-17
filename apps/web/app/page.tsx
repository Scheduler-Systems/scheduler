import HomePage from "./home-page";

// SEO metadata lives on the server-rendered page. Client-side, we redirect
// to /dashboard (signed in) or /login (otherwise) — same UX as the legacy
// Flutter web app.
export const metadata = {
  title: "Scheduler — Workforce scheduling for small teams",
  description:
    "Build shift rosters, collect employee preferences, and publish schedules in minutes. Free for teams of any size.",
};

export default function Home() {
  return <HomePage />;
}
