import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { Nav } from "@/components/Nav";
import { StatusStrip } from "@/components/StatusStrip";
import { getOverview } from "@/lib/data";
import { PROJECT_NAME, SITE_DESCRIPTION, SITE_URL } from "@/lib/site";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: PROJECT_NAME,
    template: `%s · ${PROJECT_NAME}`,
  },
  description: SITE_DESCRIPTION,
  openGraph: {
    title: PROJECT_NAME,
    description: SITE_DESCRIPTION,
    type: "website",
    siteName: PROJECT_NAME,
    images: [{ url: "/og.png", width: 1200, height: 630, alt: PROJECT_NAME }],
  },
  twitter: {
    card: "summary_large_image",
    title: PROJECT_NAME,
    description: SITE_DESCRIPTION,
    images: ["/og.png"],
  },
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const overview = getOverview();

  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <body className={`${inter.variable} ${mono.variable} font-sans`}>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-[var(--accent)] focus:px-4 focus:py-2 focus:text-white"
        >
          Skip to content
        </a>

        <Nav />
        <StatusStrip freeze={overview.freeze} />

        <main id="main" className="mx-auto max-w-content px-4 py-10 sm:px-6">
          {children}
        </main>

        <footer className="mt-16 border-t border-[var(--line)] bg-[var(--surface-sunken)]">
          <div className="mx-auto flex max-w-content flex-col gap-4 px-4 py-8 text-sm text-[var(--ink-muted)] sm:flex-row sm:items-start sm:justify-between sm:px-6">
            <div className="max-w-md">
              <p className="font-medium text-[var(--ink)]">{PROJECT_NAME}</p>
              <p className="mt-1.5 leading-relaxed">
                Built on Delhivery&apos;s public trip records. Agents operate on
                synthetic documents and a mock TMS, declared as scaffolding; the
                network data underneath is real.
              </p>
            </div>
            <div className="flex flex-col gap-1.5 text-xs text-[var(--ink-faint)]">
              <span>Academic coursework · 2026</span>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
