import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_ORIGIN || 'https://intheloop-publisher.giraff-online.chatgpt.site'),
  title: 'In The Loop · 运营工作台',
  description: 'In The Loop 内部内容运营与多平台发布工作台。',
  applicationName: 'In The Loop 运营工作台',
  icons: {
    icon: '/itl-logo-black.png',
    apple: '/itl-logo-black.png',
  },
  openGraph: {
    title: 'In The Loop · 运营工作台',
    description: 'In The Loop 内部运营工作台：微信公众号草稿与极客公园官网发布。',
    images: ['/og.png'],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'In The Loop · 运营工作台',
    description: 'In The Loop 内部运营工作台：微信公众号草稿与极客公园官网发布。',
    images: ['/og.png'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
