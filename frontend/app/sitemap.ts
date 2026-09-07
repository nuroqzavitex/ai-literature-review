import type { MetadataRoute } from "next";
import { siteUrl } from "./layout";

/**
 * Sitemap cố tình chỉ có một mục. Các đường dẫn còn lại đều nằm sau đăng nhập,
 * và khai chúng ở đây chỉ để danh sách trông dài hơn là tự mâu thuẫn với
 * robots.txt — Search Console sẽ báo lỗi "đã gửi nhưng bị chặn".
 */
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: siteUrl,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 1,
    },
  ];
}
