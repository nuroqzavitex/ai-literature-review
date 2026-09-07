import type { Metadata } from "next";

/**
 * Trang đăng nhập không được vào chỉ mục: nó không có nội dung để đọc, và một
 * kết quả tìm kiếm dẫn thẳng tới màn đăng nhập là kết quả vô ích.
 * robots.txt chặn thu thập; thẻ này chặn lập chỉ mục kể cả khi có nơi khác
 * trỏ link tới — hai lớp lo hai việc khác nhau.
 */
export const metadata: Metadata = {
  title: "Đăng nhập",
  robots: { index: false, follow: true },
};

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return children;
}
