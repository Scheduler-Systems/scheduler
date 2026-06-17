import type { Metadata, Viewport } from "next";
import { Montserrat, Raleway } from "next/font/google";
import { AuthProvider } from "@/lib/auth-context";
import { BillingProvider } from "@/lib/billing-context";
import { I18nProvider } from "@/lib/i18n-context";
import "./globals.css";

// Montserrat matches the Flutter app's FlutterFlow theme (display + body).
// Body/bodySmall default to weight 600 in FlutterFlow, so we preload semibold.
// Subsets cover EN, ES, and Hebrew diacritics are served by the system fallback.
const montserrat = Montserrat({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-montserrat",
  display: "swap",
});

// Raleway is the FlutterFlow button face (FFButtonWidget) and the Choose-Role
// subtitle face — loaded in Flutter as `Raleway:400,400i,700,700i,900,900i`.
// Exposed as `--font-raleway` (consumed by --font-button / the AppBar action).
const raleway = Raleway({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "700", "900"],
  variable: "--font-raleway",
  display: "swap",
});

const SITE_URL = "https://scheduler-web-next.web.app";
const SITE_TITLE = "Scheduler — Workforce scheduling for small teams";
const SITE_DESC =
  "Build shift rosters, collect employee preferences, and publish schedules in minutes. Free for teams of any size.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: SITE_TITLE,
    template: "%s · Scheduler",
  },
  description: SITE_DESC,
  applicationName: "Scheduler",
  keywords: [
    "workforce scheduling",
    "shift scheduler",
    "employee scheduling",
    "team scheduler",
    "roster builder",
    "rota app",
  ],
  authors: [{ name: "Scheduler Systems" }],
  creator: "Scheduler Systems",
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: "Scheduler",
    title: SITE_TITLE,
    description: SITE_DESC,
    locale: "en_US",
  },
  twitter: {
    card: "summary",
    title: SITE_TITLE,
    description: SITE_DESC,
  },
  alternates: {
    canonical: SITE_URL,
  },
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  // Primary purple #6a0dad — matches the Flutter FlutterFlow theme primary
  themeColor: "#6a0dad",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // Default lang/dir are server-rendered; I18nProvider updates them on mount.
  // suppressHydrationWarning lets the locale switch happen without a hydration
  // mismatch error.
  return (
    <html
      lang="en"
      dir="ltr"
      suppressHydrationWarning
      className={`${montserrat.variable} ${raleway.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-gray-50 text-gray-900">
        <I18nProvider>
          <AuthProvider>
            <BillingProvider>{children}</BillingProvider>
          </AuthProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
