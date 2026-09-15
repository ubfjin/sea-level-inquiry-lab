import type { Metadata } from "next";
import "./globals.css";

function metadataOrigin(): URL {
  const configuredUrl = process.env.NEXT_PUBLIC_SITE_URL?.trim();
  const vercelUrl = process.env.VERCEL_PROJECT_PRODUCTION_URL?.trim();
  return new URL(configuredUrl || (vercelUrl ? `https://${vercelUrl}` : "http://localhost:3000"));
}

export const metadata: Metadata = {
  metadataBase: metadataOrigin(),
  title: "해수면 탐구실 | 한반도 주변 해수면 데이터",
  description: "학생들이 월평균 해수면 자료를 지도와 그래프로 탐구하는 교육용 과학 데이터 플랫폼",
  openGraph: {
    title: "해수면 탐구실",
    description: "월평균 해수면 자료를 지도와 그래프로 직접 탐구해 보세요.",
    type: "website",
    locale: "ko_KR",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className="antialiased">{children}</body>
    </html>
  );
}
