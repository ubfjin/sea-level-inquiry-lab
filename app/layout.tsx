import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "해수면 탐구실 | 한반도 주변 해수면 데이터",
  description: "학생들이 월평균 해수면 자료를 지도와 그래프로 탐구하는 교육용 과학 데이터 플랫폼",
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
