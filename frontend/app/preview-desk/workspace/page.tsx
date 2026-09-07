"use client";
/**
 * Trang xem thử KHUNG workspace — CHỈ CHẠY Ở DEV.
 *
 * Workspace nằm sau đăng nhập và gắn chặt với dữ liệu phiên chat, nên không
 * dựng lại được bằng fixture. Trang này chép đúng markup phần KHUNG (sidebar +
 * thanh tiêu đề + vùng chat rỗng) và để nguyên CSS thật tô lên, đủ để kiểm
 * bảng màu, con dấu và kiểu chữ ở mọi chiều rộng màn hình.
 */
import { notFound } from "next/navigation";

const PROJECTS: Array<[string, string[]]> = [
  ["Mạng nơ-ron đồ thị trong khám phá thuốc", ["Kiến trúc GNN cho ái lực liên kết", "Biểu diễn phân tử"]],
  ["Mamba cho chuỗi thời gian lâm sàng", ["MIMIC-IV benchmark"]],
  ["Tấn công quyền riêng tư trong học liên kết", []],
];

export default function WorkspaceShellPreview() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <main className="claude-shell">
      <aside className="claude-sidebar">
        <div className="claude-brand">
          <span className="claude-mark" aria-hidden="true"><span>L</span></span>
          <span>LitReview</span>
        </div>
        <a className="claude-dashboard-link claude-dashboard-top" href="/dashboard">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
          <span>Dashboard</span>
        </a>
        <button className="claude-new-project" type="button"><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square"><path d="M8 3v10M3 8h10" /></svg>Dự án mới</button>
        <div className="claude-side-label">Projects</div>
        <nav className="claude-project-list" aria-label="Projects">
          {PROJECTS.map(([name, chats], i) => (
            <section className="claude-project-tree" key={name}>
              <div className="claude-project-row">
                <button className={i === 0 ? "active" : ""} type="button">
                  <svg className="folder" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M3.5 7.5h6l2 2h9v7.2a2.3 2.3 0 0 1-2.3 2.3H5.8a2.3 2.3 0 0 1-2.3-2.3z" />
                  </svg>
                  <span>{name}</span>
                </button>
              </div>
              <div className="claude-project-chats">
                {chats.map((c) => (
                  <div className="claude-session-row" key={c}>
                    <button className="claude-session-select" type="button">{c}</button>
                  </div>
                ))}
                {!chats.length && <span className="claude-no-chats">Chưa có chat</span>}
              </div>
            </section>
          ))}
        </nav>
        <div className="claude-sidebar-bottom"><span>Nguyễn Huy</span></div>
      </aside>

      <section className="claude-chat">
        <header className="claude-chat-header">
          <div><span>LitReview</span><h2>Bạn muốn nghiên cứu điều gì?</h2></div>
        </header>
        <div className="claude-welcome">
          <h2>Chào bạn, mình là Trợ lý nghiên cứu.</h2>
          <p>Mình hỗ trợ tìm, đọc và tổng hợp bài báo hoặc kiến thức học thuật.</p>
        </div>
      </section>
    </main>
  );
}
