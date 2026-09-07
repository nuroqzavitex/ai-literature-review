"use client";
/**
 * Trang xem thử bàn nghiên cứu — CHỈ CHẠY Ở MÔI TRƯỜNG DEV.
 *
 * Toàn bộ dashboard nằm sau đăng nhập, nên trước đây không có cách nào xem
 * giao diện mà không có phiên Clerk thật: mọi thay đổi bố cục đều phải sửa mù.
 * Trang này dựng đúng component hiển thị thật bằng dữ liệu mẫu, nên thấy được
 * bố cục ở mọi chiều rộng màn hình.
 *
 * Chặn ở production là bắt buộc: dữ liệu dưới đây là bịa, và một trang công
 * khai bày ra dự án giả như thật thì không khác gì nói dối người xem.
 */
import { notFound } from "next/navigation";
import { DeskHomeView } from "../_components/DeskHome";
import type { Assignment, Project, Review, ReviewFeedback } from "../_components/workspace-types";

const projects = [
  { project_id: "prj_9f2a1c4e7b", name: "Mạng nơ-ron đồ thị trong khám phá thuốc", description: "Tổng hợp kiến trúc GNN cho dự đoán tính chất phân tử và sàng lọc ảo.", project_role: "owner", updated_at: "2026-08-20T10:00:00Z" },
  { project_id: "prj_44bd0e91aa", name: "Mamba cho chuỗi thời gian lâm sàng", description: "So sánh state space model với Transformer trên dữ liệu ICU.", project_role: "researcher", updated_at: "2026-08-19T08:30:00Z" },
  { project_id: "prj_7c15ab3d20", name: "Tấn công quyền riêng tư trong học liên kết", description: "", project_role: "reviewer", updated_at: "2026-08-17T14:05:00Z" },
] as unknown as Project[];

const reviewsByProject = {
  prj_9f2a1c4e7b: [
    { job_id: "job_a1", topic: "Kiến trúc GNN nào cho dự đoán ái lực liên kết protein–ligand?", status: "running" },
    { job_id: "job_a2", topic: "Biểu diễn phân tử", status: "approved" },
    { job_id: "job_a3", topic: "Mô hình sinh phân tử", status: "hitl_waiting" },
  ],
  prj_44bd0e91aa: [{ job_id: "job_b1", topic: "MIMIC-IV benchmark", status: "approved" }],
  prj_7c15ab3d20: [],
} as unknown as Record<string, Review[]>;

const assignments = [
  { assignment_id: "as_1", project_id: "prj_44bd0e91aa", job_id: "job_b1", project_name: "Mamba cho chuỗi thời gian lâm sàng", topic: "Kiểm chứng kết luận về độ trễ suy luận trên chuỗi dài", review_status: "hitl_waiting", requested_by: "Trần Minh Quân", status: "assigned" },
  { assignment_id: "as_2", project_id: "prj_9f2a1c4e7b", job_id: "job_a3", project_name: "Mạng nơ-ron đồ thị trong khám phá thuốc", topic: "Rà soát trích dẫn phần mô hình sinh", review_status: "changes_requested", requested_by: "Lê Thu Hà", status: "assigned" },
] as unknown as Assignment[];

const feedback = [
  { feedback_id: "fb_1", verdict: "approve", note: "Bằng chứng đủ, trích dẫn khớp nguyên văn.", created_at: "2026-08-20T09:00:00Z" },
  { feedback_id: "fb_2", verdict: "request_more_evidence", note: "Cần thêm nguồn cho luận điểm về độ ổn định.", created_at: "2026-08-19T16:20:00Z" },
] as unknown as ReviewFeedback[];

export default function PreviewPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <DeskHomeView projects={projects} assignments={assignments} reviewsByProject={reviewsByProject} feedback={feedback} slotAvatar={<span className="v2-user">NH</span>} />;
}
