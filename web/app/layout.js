import { Inter, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

// A real UI face and a companion mono. Figures live in the mono so columns
// align and a price never reflows as digits change.
const sans = Inter({
  subsets: ["latin", "latin-ext"],
  variable: "--font-sans",
  display: "swap",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata = {
  title: "FinAdvisor",
  description: "SEC EDGAR verisinden deterministik finansal analiz",
};

export default function RootLayout({ children }) {
  return (
    <html lang="tr" className={`${sans.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
