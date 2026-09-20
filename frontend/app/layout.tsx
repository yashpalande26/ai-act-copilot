import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/sonner";

/**
 * Type pairing.
 *
 * Instrument Serif carries the wordmark and display headlines: a refined
 * editorial face that reads as institutional rather than startup, which is the
 * register a compliance tool needs. Geist handles all UI and body text, where
 * a grotesk is more legible at small sizes and in dense legal prose. The
 * contrast between the two is the point; using one face for both would lose
 * the editorial voice.
 */
const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const display = Instrument_Serif({
  variable: "--font-display",
  subsets: ["latin"],
  weight: "400",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AI Act Copilot | Know your EU AI Act obligations",
  description:
    "Ask what the EU AI Act requires of your AI system and get answers quoted from the official consolidated text, with a citation on every claim.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${display.variable} h-full antialiased`}
    >
      <body className="bg-paper text-ink flex min-h-full flex-col">
        {children}
        <Toaster position="top-center" />
      </body>
    </html>
  );
}
