import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { LanguageProvider } from "./_components/language-context";
import "./globals.css";

/**
 * Địa chỉ công khai của site. PHẢI đặt NEXT_PUBLIC_SITE_URL khi triển khai thật —
 * canonical, ảnh Open Graph và sitemap đều dựng từ đây, và nếu để nguyên
 * localhost thì mọi liên kết chia sẻ sẽ trỏ về máy của người dùng.
 */
export const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

const description =
  "Bàn nghiên cứu dựa trên bằng chứng: tự động tìm, đọc và tổng hợp bài báo khoa học, " +
  "mọi kết luận đều kèm trích dẫn truy được về đúng bài báo gốc và phải qua một lượt duyệt độc lập.";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: { default: "LitReview — Bàn nghiên cứu dựa trên bằng chứng", template: "%s · LitReview" },
  description,
  applicationName: "LitReview",
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    siteName: "LitReview",
    locale: "vi_VN",
    url: "/",
    title: "LitReview — Bàn nghiên cứu dựa trên bằng chứng",
    description,
    // Ảnh lấy từ app/opengraph-image.tsx, Next tự gắn kích thước và kiểu tệp.
  },
  twitter: {
    card: "summary_large_image",
    title: "LitReview — Bàn nghiên cứu dựa trên bằng chứng",
    description,
  },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, "max-image-preview": "large", "max-snippet": -1 },
  },
  formatDetection: { telephone: false, address: false, email: false },
};

/**
 * Dữ liệu có cấu trúc. Chỉ khai những gì kiểm chứng được — không có đánh giá,
 * giá hay số người dùng, vì bịa các trường đó là con đường ngắn nhất tới một
 * án phạt thủ công của Google.
 */
const structuredData = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "LitReview",
  applicationCategory: "ResearchApplication",
  operatingSystem: "Web",
  url: siteUrl,
  description,
  inLanguage: ["vi", "en"],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  const content = <body><LanguageProvider>{children}</LanguageProvider></body>;
  return (
    <html lang="vi">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&display=swap"
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
        />
      </head>
      {publishableKey ? <ClerkProvider publishableKey={publishableKey}>{content}</ClerkProvider> : content}
    </html>
  );
}
