import type { MetadataRoute } from "next";
import { siteUrl } from "./layout";

/**
 * Chỉ trang giới thiệu là công khai. Mọi thứ sau đăng nhập đều bị chặn: chúng
 * cần phiên làm việc nên với trình thu thập chỉ là trang trống hoặc trang lỗi,
 * và để lọt vào chỉ mục thì người tìm kiếm sẽ bấm vào một kết quả cụt.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/api/", "/auth", "/dashboard", "/workspace", "/projects", "/legacy"],
      },
    ],
    sitemap: `${siteUrl}/sitemap.xml`,
    host: siteUrl,
  };
}
