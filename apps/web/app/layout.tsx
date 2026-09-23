import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

const interTight = localFont({
  src: "../node_modules/@fontsource-variable/inter-tight/files/inter-tight-latin-wght-normal.woff2",
  weight: "400 600",
  style: "normal",
  display: "swap",
  variable: "--font-inter-tight",
});

export const metadata: Metadata = {
  title: "Shoulder",
  description: "A quiet space for coach-led development.",
  robots: { index: false, follow: false },
  // Home-screen install; icons come from app/icon.svg, app/apple-icon.png,
  // and app/manifest.ts.
  appleWebApp: { capable: true, title: "Shoulder", statusBarStyle: "default" },
};

export const viewport: Viewport = {
  themeColor: "#faf9f7",
  // Lets the player shell pad itself with env(safe-area-inset-*).
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={interTight.variable}>
      <body>{children}</body>
    </html>
  );
}
