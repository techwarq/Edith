import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Edith — Evolution",
  description: "Live performance, evolution and retention dashboard for Edith",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
