import type { Metadata, Viewport } from "next";
import { Familjen_Grotesk, Geist_Mono } from "next/font/google";

import "@/styles/tokens.css";
import "@/styles/base.css";

const sans = Familjen_Grotesk({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-familjen",
});

const mono = Geist_Mono({
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500"],
  variable: "--font-geist-mono",
});

export const metadata: Metadata = {
  metadataBase: new URL("http://localhost:3000"),
  title: {
    default: "Flowstate · Payment recovery with evidence",
    template: "%s · Flowstate",
  },
  description:
    "Flowstate finds the payment route that is failing, takes one bounded action, and proves what it recovered against a live control group.",
  openGraph: {
    title: "Flowstate · Payment recovery with evidence",
    description:
      "A bank starts declining. You have four minutes. Flowstate decides, guards the blast radius, and measures the recovery against a holdout.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: "#171d1c",
  colorScheme: "dark",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
