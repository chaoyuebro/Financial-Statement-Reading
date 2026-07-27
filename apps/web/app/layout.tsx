import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '财报阅读 · 辅助阅读工具',
  description: '财报与招股书辅助阅读工具（MVP）',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
