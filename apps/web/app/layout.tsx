import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { RouteProgress } from "../components/route-progress";
import { NativeBridge } from "./native-bridge";

const interTight = localFont({
  src: "../node_modules/@fontsource-variable/inter-tight/files/inter-tight-latin-wght-normal.woff2",
  weight: "400 600",
  style: "normal",
  display: "swap",
  variable: "--font-inter-tight",
});

// Display face (ADR 0022): condensed width axis for titles only.
const archivo = localFont({
  src: "../node_modules/@fontsource-variable/archivo/files/archivo-latin-wdth-normal.woff2",
  weight: "100 900",
  style: "normal",
  display: "swap",
  variable: "--font-archivo",
  declarations: [{ prop: "font-stretch", value: "62% 125%" }],
});

// Data face (ADR 0026): timestamps, halves, shirt numbers, match ids.
const geistMono = localFont({
  src: "../node_modules/@fontsource-variable/geist-mono/files/geist-mono-latin-wght-normal.woff2",
  weight: "400 600",
  style: "normal",
  display: "swap",
  variable: "--font-geist-mono",
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
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#0a0a09" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0a09" },
  ],
  // Lets the player shell pad itself with env(safe-area-inset-*).
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${interTight.variable} ${archivo.variable} ${geistMono.variable}`}
    >
      <body>
        <RouteProgress />
        {children}
        <NativeBridge />
      </body>
    </html>
  );
}
