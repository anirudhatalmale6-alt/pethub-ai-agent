import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PetHub AI Agent",
  description: "AI-powered operations assistant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-surface-950 text-surface-200 antialiased">{children}</body>
    </html>
  );
}
