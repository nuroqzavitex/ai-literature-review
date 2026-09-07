"use client";

import { UserButton, useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useLanguage } from "./language-context";

/**
 * Scroll reveal — robust implementation.
 * Uses rAF to guarantee the hidden state is painted BEFORE the observer
 * attaches, preventing elements from flashing visible on hydration.
 */
function useScrollReveal() {
  useEffect(() => {
    // Mark all .sr elements as "ready to animate" after first paint
    const els = Array.from(document.querySelectorAll<HTMLElement>(".sr"));

    // Double rAF: ensures browser has committed the initial hidden paint
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const io = new IntersectionObserver(
          (entries) => {
            entries.forEach((e) => {
              if (e.isIntersecting) {
                // Small stagger based on data-delay attr (set in JSX)
                const delay = Number((e.target as HTMLElement).dataset.delay ?? 0);
                setTimeout(() => e.target.classList.add("sr-in"), delay);
                io.unobserve(e.target);
              }
            });
          },
          { threshold: 0.08, rootMargin: "0px 0px -40px 0px" }
        );
        els.forEach((el) => io.observe(el));
      });
    });
  }, []);
}

const T = {
  vi: {
    login: "Đăng nhập",
    start: "Bắt đầu miễn phí",
    brand_tagline: "Nghiên cứu dựa trên bằng chứng",
    menu: "Mục lục",
    menu_close: "Đóng mục lục",
    method: "Phương pháp",
    workflow: "Quy trình",
    pricing: "Bảng giá",
    demo: "Xem demo",
    demo_h2: "LitReview vận hành như thế nào?",
    demo_intro: "Theo dõi luồng làm việc thực tế, từ câu hỏi nghiên cứu đến báo cáo có thể kiểm tra lại.",
    demo_video_title: "Video demo LitReview",
    demo_watch_direct: "Xem trên YouTube ↗",
    h1a: "Một câu hỏi.",
    h1b: "Một chuỗi bằng chứng.",
    sub: "Tìm nguồn, liên kết bằng chứng, phát hiện mâu thuẫn và tạo báo cáo có thể kiểm tra lại.",
    hero_cta: "Tạo hồ sơ nghiên cứu miễn phí →",
    hero_desk: "Vào bàn nghiên cứu →",
    hero_how: "Xem hồ sơ mẫu",
    trail_label: "Chuỗi bằng chứng minh họa",
    trail: [
      { type: "NGUỒN", id: "S012", title: "Transformer-XL: Beyond a Fixed-Length Context", meta: "Dai và cộng sự · ACL 2019", status: "Độ mạnh bằng chứng 0,94", tone: "source" },
      { type: "LUẬN ĐIỂM", id: "C018", title: "Khả năng giữ ngữ cảnh giảm sau 32K token.", meta: "Được 4 nguồn hỗ trợ · Trang 7", status: "Có cơ sở 4 / 4", tone: "claim" },
      { type: "MÂU THUẪN", id: "E037", title: "Mô hình tiếng Việt suy giảm ở tác vụ văn bản dài.", meta: "Nguyen và cộng sự · 2024", status: "2 nguồn bất đồng", tone: "conflict" },
      { type: "KHOẢNG TRỐNG", id: "G03", title: "Dữ liệu miền tiếng Việt chưa được kiểm chứng đủ.", meta: "Khoảng trống nghiên cứu · 3 bài được trích dẫn", status: "Cần xem xét", tone: "gap" },
    ],
    docket_live: "● ĐANG NGHIÊN CỨU",
    dossier_q: "Transformer-XL cho văn bản dài tiếng Việt?",
    dossier_meta: "12 bài báo đã sàng lọc · 7 bằng chứng trích xuất",
    source_head: "Sổ nguồn trích dẫn",
    coverage: "Độ phủ bằng chứng 0,78",
    open_dossier: "Mở hồ sơ ↗",
    capabilities_h2: "Mỗi thao tác đều để lại dấu vết.",
    capabilities_intro: "Một bàn nghiên cứu để đọc, kiểm tra và đặt bằng chứng vào đúng chỗ.",
    capabilities_label: "Các năng lực của LitReview",
    capabilities: [
      ["Khám phá nguồn", "Tìm và chấm mức liên quan theo đề cương nghiên cứu.", "Sổ nguồn trích dẫn"],
      ["Đọc có ngữ cảnh", "Lưu passage cùng vị trí và nguồn gốc của nó.", "Trích đoạn bằng chứng"],
      ["Liên kết luận điểm", "Nối nhiều nguồn vào từng kết luận đang hình thành.", "Ma trận bằng chứng"],
      ["Thấy mâu thuẫn", "Giữ bất đồng trong hồ sơ thay vì làm phẳng nó.", "Nhật ký mâu thuẫn"],
      ["Tìm khoảng trống", "Nhìn ra câu hỏi chưa có đủ bằng chứng để kết luận.", "Khoảng trống nghiên cứu"],
      ["Tổng hợp để duyệt", "Đưa chuỗi bằng chứng vào báo cáo có thể kiểm tra lại.", "Báo cáo đã duyệt"],
    ],
    how_h2: "Từ câu hỏi đến báo cáo.",
    steps: [
      ["Định phạm vi", "Câu hỏi → tiêu chí + từ khóa.", "Đề cương nghiên cứu"],
      ["Tìm và sàng lọc", "Tìm nguồn, chấm mức liên quan.", "Sổ nguồn trích dẫn"],
      ["Trích xuất bằng chứng", "Gắn trích đoạn vào từng luận điểm.", "Ma trận bằng chứng"],
      ["Tổng hợp và duyệt", "Báo cáo → người duyệt độc lập.", "Báo cáo đã duyệt"],
    ],
    proof_h2: "Đầu ra vẫn giữ đường dẫn về nguồn.",
    proof_intro: "Báo cáo không chỉ trả lời; nó cho biết kết luận nào được hỗ trợ, còn chỗ nào cần đọc thêm và vì sao.",
    proof_label: "Mẫu báo cáo / R-001",
    proof_status: "SẴN SÀNG ĐỂ DUYỆT",
    proof_report_title: "Kết luận có điều kiện, không phải một câu trả lời vô căn cứ.",
    proof_summary: "Dữ liệu hiện có ủng hộ việc dùng Transformer-XL cho văn bản dài, nhưng độ tin cậy giảm ở tập dữ liệu tiếng Việt chuyên ngành.",
    proof_claim_label: "LUẬN ĐIỂM ĐƯỢC HỖ TRỢ / C018",
    proof_claim: "Giữ ngữ cảnh giảm khi chuỗi vượt ngưỡng dài; giới hạn này cần được kiểm tra theo từng miền dữ liệu.",
    proof_ledger_label: "Tóm tắt kiểm chứng",
    proof_metrics: [["4 / 4", "nguồn hỗ trợ"], ["3", "điểm cần kiểm tra"], ["0,78", "độ phủ bằng chứng"]],
    proof_footer: "Mọi kết luận đều quay về đoạn trích và bài báo gốc.",
    proof_link: "Tạo hồ sơ của bạn →",
    why_h2: "Thiết kế để kiểm tra.",
    principles: [
      ["Nguồn trước, kết luận sau", "Bằng chứng gắn vào từng luận điểm trước khi có báo cáo."],
      ["Thấy được quá trình", "Truy vấn, bài bị loại và giới hạn dữ liệu đều hiện rõ."],
      ["Phản biện độc lập", "Người duyệt kiểm tra mâu thuẫn trước khi duyệt báo cáo."],
      ["Tích lũy theo dự án", "Câu hỏi và bằng chứng thành hồ sơ dài hạn."],
    ],
    pricing_label: "BẢNG GIÁ",
    pricing_h2: "Bảng giá minh bạch, linh hoạt",
    pricing_intro: "Bắt đầu miễn phí. Nâng cấp khi bạn cần thêm sức mạnh.",
    pricing_popular: "Phổ biến nhất",
    pricing_billing_month: "Hàng tháng",
    pricing_billing_year: "Hàng năm",
    pricing_save: "Tiết kiệm 17%",
    pricing_billed_yearly: "thanh toán {total}đ / năm",
    pricing_note: "Cần thêm giữa chu kỳ? Nạp thêm lượt tổng hợp hoặc PDF trực tiếp trong ứng dụng — không cần đổi gói.",
    pricing_groups: ["Hạn mức sử dụng", "Tính năng nâng cao", "Lưu trữ & xuất"],
    pricing_tiers: [
      {
        id: "free",
        name: "Free",
        price: "0đ",
        price_year: "",
        price_year_equiv: "",
        price_year_total: "",
        period: "mãi mãi",
        cta: "Bắt đầu miễn phí",
        featured: false,
        subtitle: "Phù hợp để thử và học",
        features: [
          { group: 0, text: "50 credits / tháng", included: true },
          { group: 0, text: "10 tài liệu PDF / tháng", included: true },
          { group: 0, text: "4 lần tổng hợp Literature Review / tháng", included: true },
          { group: 0, text: "Mind Map miễn phí", included: true },
          { group: 1, text: "Xuất LaTeX", included: false },
          { group: 1, text: "Sandbox thử nghiệm", included: false },
          { group: 1, text: "Tạo slide từ báo cáo", included: false },
          { group: 2, text: "Lưu trữ 500 MB", included: true },
          { group: 2, text: "Nạp thêm giữa chu kỳ", included: false },
        ],
      },
      {
        id: "plus",
        name: "Plus",
        price: "99.000đ",
        price_year: "82.000đ",
        price_year_equiv: "82.000đ",
        price_year_total: "986.000",
        period: "mỗi tháng",
        cta: "Nâng cấp ngay",
        featured: true,
        subtitle: "Cho nhà nghiên cứu thường xuyên",
        features: [
          { group: 0, text: "200 credits / tháng", included: true },
          { group: 0, text: "50 tài liệu PDF / tháng", included: true },
          { group: 0, text: "20 lần tổng hợp Literature Review / tháng", included: true },
          { group: 0, text: "Mind Map miễn phí", included: true },
          { group: 1, text: "Xuất LaTeX", included: true },
          { group: 1, text: "Sandbox thử nghiệm", included: true },
          { group: 1, text: "Tạo slide từ báo cáo (10 lần / tháng)", included: true },
          { group: 2, text: "Lưu trữ 2 GB", included: true },
          { group: 2, text: "Nạp thêm giữa chu kỳ", included: true },
        ],
      },
      {
        id: "unlimited",
        name: "Lab/Team",
        price: "299.000đ",
        price_year: "248.000đ",
        price_year_equiv: "248.000đ",
        price_year_total: "2.978.000",
        period: "mỗi tháng",
        cta: "Nâng cấp ngay",
        featured: false,
        subtitle: "Dành cho lab và nhóm nghiên cứu",
        features: [
          { group: 0, text: "Credits không giới hạn", included: true },
          { group: 0, text: "Tài liệu PDF không giới hạn", included: true },
          { group: 0, text: "Tổng hợp Literature Review không giới hạn", included: true },
          { group: 0, text: "Mind Map miễn phí", included: true },
          { group: 1, text: "Xuất LaTeX", included: true },
          { group: 1, text: "Sandbox không giới hạn phiên", included: true },
          { group: 1, text: "Tạo slide không giới hạn", included: true },
          { group: 2, text: "Lưu trữ 10 GB", included: true },
        ],
      },
    ],
    cta_h2: "Bắt đầu bằng một câu hỏi.",
    cta_btn: "Tạo dự án nghiên cứu →",
    faq_h2: "Những điều cần biết trước khi bắt đầu.",
    faq_intro: "LitReview giúp tổ chức quá trình nghiên cứu; phán đoán học thuật vẫn thuộc về bạn.",
    faqs: [
      ["Mỗi luận điểm có quay về nguồn được không?", "Có. Bằng chứng được lưu cùng bài báo, đoạn trích và vị trí để người đọc có thể kiểm tra lại ngữ cảnh."],
      ["LitReview xử lý nguồn mâu thuẫn thế nào?", "Mâu thuẫn được giữ lại trong hồ sơ, thay vì bị làm phẳng thành một kết luận duy nhất."],
      ["Người duyệt làm gì?", "Người duyệt kiểm tra độ phủ bằng chứng, các nguồn và những luận điểm còn cần làm rõ trước khi duyệt báo cáo."],
      ["Có thể làm việc theo dự án không?", "Có. Mỗi dự án lưu đề cương, nguồn, bằng chứng, báo cáo và các vòng duyệt để nhóm có thể tiếp tục từ đúng ngữ cảnh."],
      ["LitReview có thay thế việc đọc bài báo gốc không?", "Không. LitReview hỗ trợ sàng lọc, tổ chức và kiểm tra; nghiên cứu nghiêm túc vẫn cần phán đoán của người đọc."],
    ],
    foot_blurb: "Nghiên cứu dựa trên bằng chứng cho những câu hỏi cần được trả lời tử tế.",
    foot_product: "Sản phẩm",
    foot_access: "Truy cập",
    foot_contact: "Liên hệ & Hỗ trợ",
    foot_product_links: [["Bàn nghiên cứu", "/dashboard"], ["Quy trình", "#workflow"], ["Bảng giá", "#pricing"]],
    foot_access_links: [["Đăng nhập", "/auth"], ["Tạo dự án", "/auth"], ["Câu hỏi thường gặp", "#faq"]],
    foot_contact_links: [
      ["Hotline: 0912 345 678", "tel:+84912345678"],
      ["Gmail: contact@litreview.vn", "mailto:contact@litreview.vn"],
      ["Facebook Fanpage", "https://facebook.com"],
      ["Cộng đồng Nghiên cứu", "https://facebook.com"],
    ],
    foot_copy: "© 2026 LitReview · Không có nguồn, không có kết luận.",
    back_to_top: "Về đầu trang",
  },
  en: {
    login: "Sign in",
    start: "Start for free",
    brand_tagline: "Evidence-first research",
    menu: "Menu",
    menu_close: "Close menu",
    method: "Method",
    workflow: "Workflow",
    pricing: "Pricing",
    demo: "See demo",
    demo_h2: "How does LitReview work?",
    demo_intro: "Follow the working flow from a research question to a report you can inspect.",
    demo_video_title: "LitReview product demo",
    demo_watch_direct: "Watch on YouTube ↗",
    h1a: "One question.",
    h1b: "One chain of evidence.",
    sub: "From question to a fully sourced evidence trail.",
    hero_cta: "Open research desk →",
    hero_desk: "Open research desk →",
    hero_how: "See how it works",
    trail_label: "Example evidence trail",
    trail: [
      { type: "SOURCE", id: "S012", title: "Transformer-XL: Beyond a Fixed-Length Context", meta: "Dai et al. · ACL 2019", status: "Evidence strength 0.94", tone: "source" },
      { type: "CLAIM", id: "C018", title: "Long-context retention degrades beyond 32K tokens.", meta: "Supported by 4 sources · Page 7", status: "Grounded 4 / 4", tone: "claim" },
      { type: "CONFLICT", id: "E037", title: "Vietnamese models underperform on long-form tasks.", meta: "Nguyen et al. · 2024", status: "2 sources disagree", tone: "conflict" },
      { type: "GAP", id: "G03", title: "Under-tested in Vietnamese domain data.", meta: "Research gap · 3 cited papers", status: "Needs review", tone: "gap" },
    ],
    docket_live: "● LIVE RESEARCH",
    dossier_q: "Transformer-XL for long-form Vietnamese text?",
    dossier_meta: "12 screened papers · 7 extracted evidence items",
    source_head: "Source ledger",
    coverage: "Evidence coverage 0.78",
    open_dossier: "Open dossier ↗",
    capabilities_h2: "Every action leaves a trace.",
    capabilities_intro: "One research desk for reading, checking and placing evidence where it belongs.",
    capabilities_label: "LitReview capabilities",
    capabilities: [
      ["Discover sources", "Find and score relevance against the research brief.", "Source ledger"],
      ["Read in context", "Keep each passage with its location and provenance.", "Evidence excerpt"],
      ["Map claims", "Connect several sources to each emerging conclusion.", "Evidence matrix"],
      ["Surface conflict", "Keep disagreement in the dossier instead of flattening it.", "Conflict log"],
      ["Find the gaps", "See which questions do not yet have enough evidence.", "Research gaps"],
      ["Synthesize for review", "Bring the evidence trail into a report people can inspect.", "Reviewed report"],
    ],
    how_h2: "From question to report.",
    steps: [
      ["Scope the question", "Question → criteria + keywords.", "Research brief"],
      ["Find & screen", "Search sources, score relevance.", "Source ledger"],
      ["Extract evidence", "Map passages to each claim.", "Evidence matrix"],
      ["Synthesise & review", "Report → independent reviewer.", "Reviewed report"],
    ],
    proof_h2: "Every output retains its route back to the source.",
    proof_intro: "A report does more than answer: it shows which conclusions are supported, what still needs reading and why.",
    proof_label: "Report sample / R-001",
    proof_status: "READY FOR REVIEW",
    proof_report_title: "A qualified conclusion, not an unsupported answer.",
    proof_summary: "Current evidence supports using Transformer-XL for long documents, but confidence drops for specialised Vietnamese-domain data.",
    proof_claim_label: "SUPPORTED CLAIM / C018",
    proof_claim: "Context retention drops beyond a long-sequence threshold; that limit needs testing in each data domain.",
    proof_ledger_label: "Verification summary",
    proof_metrics: [["4 / 4", "supporting sources"], ["3", "points to check"], ["0.78", "evidence coverage"]],
    proof_footer: "Every conclusion links back to a passage and its original paper.",
    proof_link: "Create your dossier →",
    why_h2: "Designed for verification.",
    principles: [
      ["Sources first, conclusions later", "Evidence ties to each claim before a report is written."],
      ["See the process", "Search queries, rejected papers and data limits are all visible."],
      ["Independent challenge", "A reviewer checks contradictions before approving the report."],
      ["Accumulates by project", "Questions and evidence become a long-running dossier."],
    ],
    pricing_label: "PRICING",
    pricing_h2: "Simple, transparent pricing",
    pricing_intro: "Start free. Upgrade when you need more power.",
    pricing_popular: "Most Popular",
    pricing_billing_month: "Monthly",
    pricing_billing_year: "Yearly",
    pricing_save: "Save 17%",
    pricing_billed_yearly: "billed {total}đ / year",
    pricing_note: "Need more mid-cycle? Top up PDF uploads or synthesis runs right inside the app — no plan change needed.",
    pricing_groups: ["Monthly limits", "Advanced tools", "Storage & export"],
    pricing_tiers: [
      {
        id: "free",
        name: "Free",
        price: "0đ",
        price_year: "",
        price_year_equiv: "",
        price_year_total: "",
        period: "forever",
        cta: "Start for free",
        featured: false,
        subtitle: "Great for exploring",
        features: [
          { group: 0, text: "50 credits / month", included: true },
          { group: 0, text: "10 PDF uploads / month", included: true },
          { group: 0, text: "4 Literature Review syntheses / month", included: true },
          { group: 0, text: "Mind Map included free", included: true },
          { group: 1, text: "LaTeX export", included: false },
          { group: 1, text: "Sandbox environment", included: false },
          { group: 1, text: "Slide generation from reports", included: false },
          { group: 2, text: "500 MB storage", included: true },
          { group: 2, text: "Mid-cycle top-up", included: false },
        ],
      },
      {
        id: "plus",
        name: "Plus",
        price: "99.000đ",
        price_year: "82.000đ",
        price_year_equiv: "82.000đ",
        price_year_total: "986.000",
        period: "per month",
        cta: "Upgrade now",
        featured: true,
        subtitle: "For regular researchers",
        features: [
          { group: 0, text: "200 credits / month", included: true },
          { group: 0, text: "50 PDF uploads / month", included: true },
          { group: 0, text: "20 Literature Review syntheses / month", included: true },
          { group: 0, text: "Mind Map included free", included: true },
          { group: 1, text: "LaTeX export", included: true },
          { group: 1, text: "Sandbox environment", included: true },
          { group: 1, text: "Slide generation (10 / month)", included: true },
          { group: 2, text: "2 GB storage", included: true },
          { group: 2, text: "Mid-cycle top-up", included: true },
        ],
      },
      {
        id: "unlimited",
        name: "Lab/Team",
        price: "299.000đ",
        price_year: "248.000đ",
        price_year_equiv: "248.000đ",
        price_year_total: "2.978.000",
        period: "per month",
        cta: "Upgrade now",
        featured: false,
        subtitle: "For research labs and teams",
        features: [
          { group: 0, text: "Unlimited credits", included: true },
          { group: 0, text: "Unlimited PDF uploads", included: true },
          { group: 0, text: "Unlimited Literature Review syntheses", included: true },
          { group: 0, text: "Mind Map included free", included: true },
          { group: 1, text: "LaTeX export", included: true },
          { group: 1, text: "Unlimited sandbox sessions", included: true },
          { group: 1, text: "Unlimited slide generation", included: true },
          { group: 2, text: "10 GB storage", included: true },
        ],
      },
    ],
    cta_h2: "Start with a question.",
    cta_btn: "Create research project →",
    faq_h2: "What to know before you begin.",
    faq_intro: "LitReview helps structure research work; academic judgment remains yours.",
    faqs: [
      ["Can every claim lead back to a source?", "Yes. Evidence stays with its paper, passage and location so readers can inspect the original context."],
      ["How does LitReview handle conflicting sources?", "Disagreement stays visible as a conflict in the dossier rather than being flattened into one conclusion."],
      ["What does the reviewer do?", "A reviewer checks evidence coverage, sources and claims that still need clarification before approving a report."],
      ["Can I work by project?", "Yes. Each project holds its brief, sources, evidence, reports and review rounds so a team can continue with the right context."],
      ["Does LitReview replace reading original papers?", "No. LitReview supports screening, organisation and checking; serious research still needs the reader's judgment."],
    ],
    foot_blurb: "Evidence-first research for questions that deserve a careful answer.",
    foot_product: "Product",
    foot_access: "Access",
    foot_contact: "Contact & Support",
    foot_product_links: [["Research desk", "/dashboard"], ["Workflow", "#workflow"], ["Pricing", "#pricing"]],
    foot_access_links: [["Sign in", "/auth"], ["Create a project", "/auth"], ["Frequently asked questions", "#faq"]],
    foot_contact_links: [
      ["Hotline: (+84) 912 345 678", "tel:+84912345678"],
      ["Gmail: contact@litreview.vn", "mailto:contact@litreview.vn"],
      ["Facebook Fanpage", "https://facebook.com"],
      ["Research Community", "https://facebook.com"],
    ],
    foot_copy: "© 2026 LitReview · No source, no conclusion.",
    back_to_top: "Back to top",
  },
} as const;

const clerkConfigured = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

function AuthHeaderActions({ t }: { t: typeof T["vi"] | typeof T["en"] }) {
  if (!clerkConfigured) {
    return (
      <>
        <a className="login" href="/auth">{t.login}</a>
        <a className="btn-primary" href="/auth">{t.start}</a>
      </>
    );
  }
  return <ClerkAuthActions t={t} />;
}

function ClerkAuthActions({ t }: { t: typeof T["vi"] | typeof T["en"] }) {
  const { isLoaded, isSignedIn } = useAuth();
  if (!isLoaded) return <span className="site-auth-loading" aria-hidden="true" />;
  if (isSignedIn) return <UserButton appearance={{ elements: { avatarBox: "landing-user-avatar" } }} />;
  return (
    <>
      <a className="login" href="/auth">{t.login}</a>
      <a className="btn-primary" href="/auth">{t.start}</a>
    </>
  );
}

function HeroPrimaryCta({ t }: { t: typeof T["vi"] | typeof T["en"] }) {
  if (!clerkConfigured) {
    return <a className="btn-primary" href="/auth">{t.hero_cta}</a>;
  }
  return <ClerkHeroPrimaryCta t={t} />;
}

function ClerkHeroPrimaryCta({ t }: { t: typeof T["vi"] | typeof T["en"] }) {
  const { isLoaded, isSignedIn } = useAuth();
  const heroPrimary = isLoaded && isSignedIn
    ? { href: "/dashboard", label: t.hero_desk }
    : { href: "/auth", label: t.hero_cta };
  return <a className="btn-primary" href={heroPrimary.href}>{heroPrimary.label}</a>;
}

export default function ProductLanding() {
  const { lang, setLang } = useLanguage();
  const [openFaq, setOpenFaq] = useState<number | null>(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [billing, setBilling] = useState<"month" | "year">("month");
  useScrollReveal();

  useEffect(() => {
    if (!menuOpen) return;
    const wide = window.matchMedia("(min-width: 641px)");
    const close = () => setMenuOpen(false);
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && !(target as Element).closest?.(".site-head")) close();
    };
    wide.addEventListener("change", close);
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      wide.removeEventListener("change", close);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [menuOpen]);
  const t = T[lang];

  return (
    <div className="product-landing" id="top">

      {/* ── Header ── */}
      <header className="site-head">
        <Link className="site-logo" href="/">
          <span className="v2-mark" aria-hidden="true"><span>L</span></span>
          <span>
            <strong>LitReview</strong>
            <small>{t.brand_tagline}</small>
          </span>
        </Link>
        <nav className="site-nav" aria-label={lang === "vi" ? "Điều hướng chính" : "Primary navigation"}>
          <a href="#why">{t.method}</a>
          <a href="#demo">{t.demo}</a>
          <a href="#pricing">{t.pricing}</a>
        </nav>
        <div className="site-actions">
          <div className="lang-toggle" role="group" aria-label="Language">
            <button className={`lang-btn${lang === "vi" ? " active" : ""}`} onClick={() => setLang("vi")} aria-pressed={lang === "vi"}>VI</button>
            <button className={`lang-btn${lang === "en" ? " active" : ""}`} onClick={() => setLang("en")} aria-pressed={lang === "en"}>EN</button>
          </div>
          <AuthHeaderActions t={t} />
          <button
            type="button"
            className="nav-toggle"
            aria-expanded={menuOpen}
            aria-controls="site-menu"
            aria-label={menuOpen ? t.menu_close : t.menu}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {/* Icon vẽ tay: hai nét gạch chuyển thành dấu nhân khi mở. */}
            <svg viewBox="0 0 22 22" width="22" height="22" aria-hidden="true" focusable="false">
              <line className="nav-toggle-bar nav-toggle-bar--top" x1="3" y1="8" x2="19" y2="8" />
              <line className="nav-toggle-bar nav-toggle-bar--bottom" x1="3" y1="14" x2="19" y2="14" />
            </svg>
          </button>
        </div>

        {/* Điều hướng tầng điện thoại. Giữ trong DOM để cả mở lẫn đóng đều có
            chuyển động; `visibility` lo việc rút link khỏi thứ tự tab khi đóng. */}
        <div className={`site-menu${menuOpen ? " is-open" : ""}`} id="site-menu">
          <nav aria-label={lang === "vi" ? "Điều hướng trên điện thoại" : "Mobile navigation"}>
            <a href="#why" onClick={() => setMenuOpen(false)}>{t.method}</a>
            <a href="#demo" onClick={() => setMenuOpen(false)}>{t.demo}</a>
            <a href="#pricing" onClick={() => setMenuOpen(false)}>{t.pricing}</a>
          </nav>
          <a className="site-menu-login" href="/auth" onClick={() => setMenuOpen(false)}>{t.login}</a>
        </div>
      </header>

      <main>

        {/* ── 01 · Hero ── */}
        <section className="lp-hero">
          <div className="lp-hero-shell">
            <div className="lp-hero-body">
              <h1>
                <span className="lp-h1-line lp-h1-line--1">{t.h1a}</span>
                <em className="lp-h1-line lp-h1-line--2">{t.h1b}</em>
              </h1>
              <p className="lp-hero-sub">{t.sub}</p>
              <div className="lp-hero-actions">
                <HeroPrimaryCta t={t} />
                <a className="lp-text-link" href="#proof">{t.hero_how}</a>
              </div>
            </div>

            <ol className="lp-evidence-trail" aria-label={t.trail_label}>
              {t.trail.map((item, index) => (
                <li className={`lp-trail-card lp-trail-card--${item.tone}`} key={item.id}>
                  <span className="lp-trail-order" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                  <div className="lp-trail-content">
                    <span className="lp-trail-kicker">{item.type} / {item.id}</span>
                    <strong>{item.title}</strong>
                    <span className="lp-trail-meta">{item.meta}</span>
                    <span className="lp-trail-status">{item.status}</span>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ── 02 · Dossier preview ── */}
        <section className="lp-preview">
          <article className="dossier-paper sr">
            <div className="docket">
              <span>HỒ SƠ / NLP-VI-001</span>
              <span className="docket-live">{t.docket_live}</span>
            </div>
            <h2 className="dossier-q">{t.dossier_q}</h2>
            <p className="dossier-meta">{t.dossier_meta}</p>
            <div className="source-ledger">
              <h3 className="ledger-head">{t.source_head}</h3>
              {[
                ["01", "Transformer-XL: Beyond a Fixed-Length Context", "Dai et al. · ACL 2019", "94%"],
                ["02", "Language Models for Low-resource Languages", "Pham et al. · EMNLP 2023", "87%"],
                ["03", "Vietnamese Pre-trained Models: A Survey", "Nguyen et al. · 2024", "81%"],
              ].map(([n, title, meta, score]) => (
                <div className="ledger-row" key={n}>
                  <span className="ledger-n">{n}</span>
                  <span className="ledger-paper">
                    <strong>{title}</strong>
                    <small>{meta}</small>
                  </span>
                  <span className="ledger-score">{score}</span>
                </div>
              ))}
            </div>
            <div className="dossier-foot">
              <span className="dossier-coverage">{t.coverage}</span>
              <a className="dossier-open" href="/auth">{t.open_dossier}</a>
            </div>
          </article>
        </section>

        {/* ── 03 · Video demo ── */}
        <section className="lp-video-demo" id="demo">
          <div className="lp-video-demo-head sr">
            <h2>{t.demo_h2}</h2>
            <p>{t.demo_intro}</p>
          </div>
          <div className="lp-video-frame sr">
            <iframe
              src="https://www.youtube-nocookie.com/embed/rIwgs3dXwJc"
              title={t.demo_video_title}
              loading="lazy"
              referrerPolicy="strict-origin-when-cross-origin"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
              allowFullScreen
            />
          </div>
          <a className="lp-video-direct-link" href="https://youtu.be/rIwgs3dXwJc" target="_blank" rel="noreferrer">
            {t.demo_watch_direct}
          </a>
        </section>

        {/* ── 04 · Capabilities ── */}
        <section className="lp-capabilities" id="capabilities">
          <div className="lp-capabilities-intro sr">
            <h2>{t.capabilities_h2}</h2>
            <p>{t.capabilities_intro}</p>
          </div>
          <div className="lp-capability-list" aria-label={t.capabilities_label}>
            {t.capabilities.map(([title, body, output], i) => (
              <article className="lp-capability sr" data-delay={i * 75} key={title}>
                <span className="lp-capability-index" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
                <div className="lp-capability-copy">
                  <h3>{title}</h3>
                  <p>{body}</p>
                </div>
                <span className="lp-capability-output">{output}</span>
              </article>
            ))}
          </div>
        </section>

        {/* ── 05 · How it works ── */}
        <section className="lp-how" id="workflow">
          <h2 className="lp-how-h2 sr">{t.how_h2}</h2>
          <div className="lp-how-grid">
            {t.steps.map(([title, body, artifact], i) => (
              <div className="lp-how-step sr" data-delay={i * 90} key={title}>
                <h3>{title}</h3>
                <p>{body}</p>
                <span className="lp-how-artifact">{artifact}</span>
              </div>
            ))}
          </div>
        </section>

        {/* ── 06 · Verifiable output ── */}
        <section className="lp-proof" id="proof">
          <div className="lp-proof-head sr">
            <h2>{t.proof_h2}</h2>
            <p>{t.proof_intro}</p>
          </div>
          <article className="lp-report-sample sr">
            <header className="lp-report-head">
              <span>{t.proof_label}</span>
              <span>{t.proof_status}</span>
            </header>
            <div className="lp-report-body">
              <div className="lp-report-main">
                <h3>{t.proof_report_title}</h3>
                <p>{t.proof_summary}</p>
                <div className="lp-report-claim">
                  <span>{t.proof_claim_label}</span>
                  <strong>{t.proof_claim}</strong>
                </div>
              </div>
              <aside className="lp-report-ledger" aria-label={t.proof_ledger_label}>
                <span>{t.proof_ledger_label}</span>
                {t.proof_metrics.map(([value, label]) => (
                  <div key={label}><b>{value}</b><small>{label}</small></div>
                ))}
              </aside>
            </div>
            <footer className="lp-report-foot">
              <span>{t.proof_footer}</span>
              <a href="/auth">{t.proof_link}</a>
            </footer>
          </article>
        </section>

        {/* ── 07 · Why ── */}
        <section className="lp-why" id="why">
          <h2 className="lp-why-h2 sr">{t.why_h2}</h2>
          <div className="lp-why-grid">
            {t.principles.map(([title, body], i) => (
              <article className="lp-principle sr" data-delay={i * 90} key={title}>
                <h3>{title}</h3>
                <p>{body}</p>
              </article>
            ))}
          </div>
        </section>

        {/* ── 08 · Pricing ── */}
        <section className="lp-pricing" id="pricing">
          <div className="lp-pricing-head sr">
            <span className="eyebrow">{t.pricing_label}</span>
            <h2>{t.pricing_h2}</h2>
            <p>{t.pricing_intro}</p>
            {/* Billing toggle */}
            <div className="lp-billing-toggle" role="group" aria-label="Billing cycle">
              <button
                className={`lp-billing-btn${billing === "month" ? " is-active" : ""}`}
                onClick={() => setBilling("month")}
                type="button"
                aria-pressed={billing === "month"}
              >
                {t.pricing_billing_month}
              </button>
              <button
                className={`lp-billing-btn${billing === "year" ? " is-active" : ""}`}
                onClick={() => setBilling("year")}
                type="button"
                aria-pressed={billing === "year"}
              >
                {t.pricing_billing_year}
                <span className="lp-billing-save">{t.pricing_save}</span>
              </button>
            </div>
          </div>
          <div className="lp-pricing-grid">
            {t.pricing_tiers.map((tier, idx) => {
              const groups = t.pricing_groups as readonly string[];
              const allFeatures = tier.features as unknown as { group: number; text: string; included: boolean }[];
              const byGroup: { label: string; items: { text: string; included: boolean }[] }[] = groups.map((label, g) => ({
                label,
                items: allFeatures.filter((f) => f.group === g),
              }));
              const tierAny = tier as { price_year?: string; price_year_total?: string; subtitle?: string };
              const isYearly = billing === "year" && !!tierAny.price_year;
              const displayPrice = isYearly ? tierAny.price_year! : tier.price;
              const billedNote = isYearly && tierAny.price_year_total
                ? t.pricing_billed_yearly.replace("{total}", tierAny.price_year_total)
                : null;
              return (
                <article
                  className={`lp-pricing-card${tier.featured ? " is-featured" : ""} sr`}
                  data-delay={idx * 80}
                  key={tier.id}
                >
                  {tier.featured && (
                    <div className="lp-pricing-badge">{t.pricing_popular}</div>
                  )}
                  <div className="lp-pricing-card-head">
                    <div className="lp-pricing-name-row">
                      <h3>{tier.name}</h3>
                      <small className="lp-pricing-subtitle">{tierAny.subtitle}</small>
                    </div>
                    <div className="lp-pricing-price">
                      <div className="lp-pricing-price-row">
                        {isYearly && (
                          <s className="lp-pricing-price-old">{tier.price}</s>
                        )}
                        <strong>{displayPrice}</strong>
                        <span>{tier.period}</span>
                      </div>
                      {billedNote && (
                        <small className="lp-pricing-billed-note">{billedNote}</small>
                      )}
                    </div>
                    <a
                      className={tier.featured ? "lp-pricing-btn is-primary" : "lp-pricing-btn is-outline"}
                      href="/auth"
                    >
                      {tier.cta}
                    </a>
                  </div>
                  <div className="lp-pricing-features-body">
                    {byGroup.map(({ label, items }) =>
                      items.length === 0 ? null : (
                        <div className="lp-pricing-group" key={label}>
                          <span className="lp-pricing-group-label">{label}</span>
                          <ul className="lp-pricing-features">
                            {items.map((feat, fIdx) => (
                              <li
                                key={fIdx}
                                className={feat.included ? "is-included" : "is-excluded"}
                              >
                                <span className="lp-pricing-icon" aria-hidden="true">
                                  {feat.included ? (
                                    <svg viewBox="0 0 16 16" width="14" height="14" fill="none">
                                      <circle cx="8" cy="8" r="7.2" stroke="currentColor" strokeWidth="1.6" />
                                      <path d="M5 8.2l2.1 2.1 4.2-4.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                                    </svg>
                                  ) : (
                                    <svg viewBox="0 0 16 16" width="14" height="14" fill="none">
                                      <circle cx="8" cy="8" r="7.2" stroke="currentColor" strokeWidth="1.6" />
                                      <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                                    </svg>
                                  )}
                                </span>
                                <span>{feat.text}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )
                    )}
                  </div>
                </article>
              );
            })}
          </div>
          <p className="lp-pricing-note sr" data-delay={240}>
            {t.pricing_note}
          </p>
        </section>

        {/* ── 09 · FAQ ── */}
        <section className="lp-faq" id="faq">
          <div className="lp-faq-head sr">
            <h2>{t.faq_h2}</h2>
            <p>{t.faq_intro}</p>
          </div>
          <div className="lp-faq-list">
            {t.faqs.map(([question, answer], index) => {
              const isOpen = openFaq === index;
              return (
                <article className={`lp-faq-item${isOpen ? " is-open" : ""} sr`} data-delay={index * 60} key={question}>
                  <h3>
                    <button aria-expanded={isOpen} aria-controls={`faq-answer-${index}`} onClick={() => setOpenFaq(isOpen ? null : index)} type="button">
                      <span>{question}</span><i aria-hidden="true" />
                    </button>
                  </h3>
                  <div className="lp-faq-answer" id={`faq-answer-${index}`} role="region">
                    <p>{answer}</p>
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        {/* ── 09 · CTA ── */}
        <section className="lp-cta sr">
          <h2>{t.cta_h2}</h2>
          <a className="btn-primary" href="/auth">{t.cta_btn}</a>
        </section>

      </main>

      <footer className="site-foot">
        <div className="site-foot-main">
          <div className="site-foot-brand">
            <Link className="site-logo" href="/"><span className="v2-mark" aria-hidden="true"><span>L</span></span><strong>LitReview</strong></Link>
            <p>{t.foot_blurb}</p>
          </div>
          <div className="site-foot-links"><h2>{t.foot_product}</h2>{t.foot_product_links.map(([label, href]) => <a href={href} key={`${label}-${href}`}>{label}</a>)}</div>
          <div className="site-foot-links"><h2>{t.foot_access}</h2>{t.foot_access_links.map(([label, href]) => <a href={href} key={`${label}-${href}`}>{label}</a>)}</div>
          <div className="site-foot-links"><h2>{t.foot_contact}</h2>{t.foot_contact_links.map(([label, href]) => <a href={href} key={`${label}-${href}`} target={href.startsWith("http") ? "_blank" : undefined} rel={href.startsWith("http") ? "noopener noreferrer" : undefined}>{label}</a>)}</div>
        </div>
        <div className="site-foot-bottom"><span>{t.foot_copy}</span><a aria-label={t.back_to_top} href="#top">↑</a></div>
      </footer>
    </div>
  );
}
