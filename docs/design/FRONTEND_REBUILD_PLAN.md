# Kế hoạch xây lại Frontend V2 — LitReview (Cập nhật đầy đủ)

> Historical implementation plan. Nhiều route/component trong checklist đã có
> trong `frontend/app/`; không dùng trạng thái checkbox bên dưới để kết luận UI
> hiện tại đã hay chưa triển khai.

---

## 🔴 Lỗi cơ bản của web hiện tại cần sửa trong lần rebuild này

> Phân tích từ source code `page.tsx` (1260 dòng), `globals.css` (2724 dòng) và `workspace.module.css`.

### 🔴 Critical (Gây vỡ UX nặng)

| # | Lỗi | Vị trí | Fix |
|---|---|---|---|
| C1 | **Toàn bộ sidebar dùng dark navy gradient** (`radial-gradient`, `navy-950`) — trái ngược với design V2 | `globals.css:78-81` | Xóa, thay bằng sidebar đen mực (`--ink #172238`) |
| C2 | **Font Inter** — không phải IBM Plex Sans | `globals.css:38` | Thay bằng IBM Plex Sans + Source Serif 4 + IBM Plex Mono |
| C3 | **Button primary dùng gradient xanh navy** (`linear-gradient #246bff → #1455d5`) — sai hoàn toàn | `globals.css:432` | Thay bằng ink + coral shadow offset (offset button style) |
| C4 | **Trang chưa có Landing Page** — user vào là thấy ngay màn hình workspace/login, không có trang giới thiệu | `page.tsx:274` | Build `index.html` thành `app/page.tsx` riêng |
| C5 | **Cả file `page.tsx` monolith 1260 dòng** — không tách route, không tách component | `page.tsx` toàn bộ | Tách thành Next.js routes + components |

### 🟡 Major (Ảnh hưởng lớn đến visual/UX)

| # | Lỗi | Vị trí | Fix |
|---|---|---|---|
| M1 | **Avatar user** dùng `linear-gradient(135deg, #38bdf8, #1e40af)` — gradient AI | `globals.css:348` | Thay bằng `--coral` background, hình vuông (border-radius: 2px) |
| M2 | **Topbar** có `backdrop-filter: blur(12px)` + `rgba(255,255,255,0.94)` — glass effect, không editorial | `globals.css:253` | Thay bằng solid `--paper-bright`, border-bottom `--rule` |
| M3 | **Card bo tròn nhiều** — `border-radius: 11px, 12px` — không đúng design V2 (max 4px) | `globals.css:463,566` | Tất cả radius → 2-4px |
| M4 | **`createReviewCard` dùng radial-gradient** xanh navy | `globals.css:577` | Xóa gradient, dùng solid `--paper-bright` |
| M5 | **Status badges** lẫn tiếng Anh/tiếng Việt không nhất quán | `page.tsx:143-151` | Dùng i18n, phân tách rõ VI/EN |
| M6 | **Workflow steps** hardcode text tiếng Anh lẫn Việt | `page.tsx:154-161` | Dùng i18n |
| M7 | **Không có nút chuyển ngôn ngữ VI/EN** ở bất kỳ đâu | Toàn bộ | Thêm `LangToggle` component |
| M8 | **`sideNav button.active`** dùng `linear-gradient` xanh navy + `box-shadow inset cyan` | `globals.css:173-174` | Thay bằng `box-shadow: inset 3px 0 0 var(--coral)` |
| M9 | **`.breadcrumb`** màu `--blue-700` — sai palette | `globals.css:378` | Thay bằng `--coral` hoặc `--teal` |
| M10 | **`workspaceSearch`** focus state dùng blue (`#93b6ff`, `rgba(36,106,255,0.1)`) | `globals.css:271-273` | Thay bằng coral/teal focus ring |

### 🟢 Minor (Cần sửa nhưng không vỡ layout)

| # | Lỗi | Vị trí | Fix |
|---|---|---|---|
| m1 | **`brandMark`** dùng `border-radius: 11px` và `rgba(35,217,242,0.1)` cyan | `globals.css:100-103` | Thay bằng `--coral`, border-radius 2px |
| m2 | **Màu dot/badge** dùng `#36d9a3` (cyan-green) | `globals.css:209` | Thay bằng `--green: #2f7653` |
| m3 | **`kbd`** styling dùng blue palette | `globals.css:293-302` | Thay bằng paper/ink palette |
| m4 | **`metricIcon.blue`** màu `#2366e9, #e8f0ff` | `globals.css:479` | Thay bằng `--teal-soft, --teal` |
| m5 | **Error box** border `#f1b9bd`, text `#98393f` — không match design tokens | `globals.css:538-541` | Thay bằng `--red: #b44933, --red-soft` |
| m6 | **`globals.css` có 2724 dòng** CSS cũ sẽ conflict với design mới | Toàn bộ file | Xóa và viết lại từ đầu |
| m7 | **Font weight dùng giá trị lạ** (`font-weight: 640, 760, 820`) không hợp lệ CSS chuẩn | `globals.css nhiều nơi` | Thay bằng giá trị chuẩn: 400, 500, 600, 700 |
| m8 | **`configuredMessage()`** trả về text tiếng Anh lẫn Việt | `page.tsx:258-268` | i18n cả phần này |
| m9 | **Không có meta tags SEO** (`og:image`, `description`, `keywords`) | `layout.tsx` | Thêm đầy đủ meta tags |
| m10 | **Không có `favicon`** phù hợp với brand V2 | `layout.tsx` | Thêm favicon `L` đỏ coral |

---

## Quyết định kiến trúc

| Vấn đề | Quyết định |
|---|---|
| Cấu trúc | **Tách thành nhiều file component** — không giữ monolith 1260 dòng |
| Routing | **Next.js App Router** — mỗi màn hình là 1 route riêng |
| CSS | Xóa `globals.css` cũ (2724 dòng) + `workspace.module.css`, viết lại từ `_editorial.css` |
| i18n | **Context-based** — 1 file JSON per lang, không cần thư viện |
| Dark mode | **CSS custom properties** — chuẩn bị token, chưa có UI toggle |
| Font | IBM Plex Sans (UI) + Source Serif 4 (headings/body dài) + IBM Plex Mono (meta/code) |

---

## Cấu trúc file sau khi rebuild

```
frontend/app/
├── globals.css              ← Viết lại hoàn toàn từ _editorial.css mockup
├── layout.tsx               ← Thêm: LangProvider, meta tags SEO, favicon
│
├── page.tsx                 ← Landing page (index.html mockup)
├── auth/page.tsx            ← Auth screen (01_auth.html)
├── dashboard/page.tsx       ← Dashboard (02_home.html)
├── projects/
│   ├── new/page.tsx         ← Create project (02_create_project.html)
│   └── [id]/
│       ├── page.tsx         ← Project workspace (03_project.html)
│       ├── loading/page.tsx ← Agent running (04_loading.html)
│       └── reports/[reportId]/page.tsx ← Report reader
│
├── _components/
│   ├── Sidebar.tsx          ← Sidebar dùng chung
│   ├── Topbar.tsx           ← Topbar dùng chung
│   ├── LangToggle.tsx       ← Nút VI/EN (pill toggle)
│   └── ThemeToggle.tsx      ← Dark mode toggle (prep)
│
└── _i18n/
    ├── vi.json
    ├── en.json
    └── context.tsx
```

---

## Phase 0 — Setup & Dọn dẹp (Ngày 1, sáng)

- [ ] Xóa `globals.css` cũ (2724 dòng), viết lại từ `_editorial.css`
- [ ] Xóa `workspace.module.css`
- [ ] Sửa `layout.tsx`: thêm Google Fonts preconnect, meta tags SEO, favicon
- [ ] Tạo `_i18n/vi.json` + `en.json` + `context.tsx`
- [ ] Tạo folder structure routes

### `globals.css` mới — Design tokens:
```css
:root {
  --ink:          #172238;   /* Mực xanh đen */
  --paper:        #f4f1ea;   /* Giấy ngà */
  --paper-bright: #fffdf8;   /* Giấy trắng sáng */
  --coral:        #d04f35;   /* Accent đỏ gạch */
  --rule:         #d7d1c6;   /* Border/line */
  --g50:  #f4f1ea; --g100: #ece8df; --g200: #ddd8ce;
  --g300: #c9c2b6; --g400: #a49c90; --g500: #756e65;
  --g600: #5d574f; --g700: #3e3a35; --g800: #292825; --g900: #171a1f;
  --green: #2f7653; --green-soft: #e6efe9;
  --amber: #b86a2f; --amber-soft: #f6eadc;
  --red:   #b44933; --red-soft:   #f5e7e3;
  --teal:  #274c9b; --teal-soft:  #e8edf7;
  --sh-sm: 0 1px 0 rgba(23,34,56,.05);
  --sh-md: 0 8px 24px rgba(23,34,56,.07);
  --r: 4px;
}
html.dark {  /* Prep tokens — chưa có UI */
  --ink: #f4f1ea; --paper: #172238; --paper-bright: #1e2d3d; --rule: #2e3e55;
}
body { font-family: 'IBM Plex Sans', sans-serif; background: var(--paper); color: var(--ink); }
```

---

## Phase 1 — Landing Page (Ngày 1, chiều)

**Route:** `/` → `app/page.tsx`
**Fix bugs:** C4, M7, m9, m10

### Sections:
| Section | Nội dung |
|---|---|
| Header | Logo `LR` coral, nav links, **[VI][EN] toggle**, nút Đăng nhập + Bắt đầu |
| Hero 2 cột | Copy + dossier mẫu (static data) |
| Manifesto | 4 nguyên tắc, nền `--ink` |
| Workflow | 4 bước, final CTA |
| Footer | Tagline mono |

---

## Phase 2 — Auth Screen (Ngày 2, sáng)

**Route:** `/auth` → `app/auth/page.tsx`
**Fix bugs:** M5, m8

### Nội dung:
- Card centered, logo LR coral
- Clerk `SignInButton` + `SignUpButton` styled đúng V2
- 3 feature rows bên dưới
- Tất cả text i18n

---

## Phase 3 — Dashboard (Ngày 2, chiều)

**Route:** `/dashboard` → `app/dashboard/page.tsx`
**Fix bugs:** C1, C2, C3, M1, M2, M3, M8, m1, m4

### Layout:
- Sidebar 244px: ink background, coral accent, nav active = `inset 3px 0 0 coral`
- Topbar: solid paper-bright, border `--rule`, avatar coral vuông
- Stats row 3 ô
- Pending reviews (ưu tiên cao)
- Project registry dạng bảng

---

## Phase 4 — Create Project (Ngày 3, sáng)

**Route:** `/projects/new` → `app/projects/new/page.tsx`
**Fix bugs:** M3, M4

- Breadcrumb coral
- Card form: input focus = coral ring
- Note box: paper-bright + coral border-left

---

## Phase 5 — Project Workspace (Ngày 3, chiều)

**Route:** `/projects/[id]` → `app/projects/[id]/page.tsx`
**Fix bugs:** C5, M6, M9, M10

- Layout 3 cột
- Câu hỏi mới: query box `border-left: 4px solid coral`
- Text i18n
- Mobile: ẩn 2 cột phụ

---

## Phase 6 — Agent Loading (Ngày 4, sáng)

**Route:** `/projects/[id]/loading`
**Fix bugs:** M6

- Progress steps: coral fill, không phải blue
- Terminal log: `--ink` background, `IBM Plex Mono`
- Text i18n

---

## Phase 7 — Report Reader (Ngày 4, chiều)

**Route:** `/projects/[id]/reports/[reportId]`
**Fix bugs:** M3, M5

- Report: Source Serif 4, tab navigation
- Evidence Matrix: ink header, rule border
- Copilot: paper background

---

## Tính năng xuyên suốt

### Language Toggle (VI/EN)
```
UI: pill [VI] [EN] trong header (landing) + sidebar (app)
State: LangContext — không reload trang
Mặc định: VI
Lưu vào: localStorage key 'litreview.lang'
```

### Dark Mode Prep
```
Tokens: đã có trong globals.css (html.dark {})
Toggle: ThemeToggle component (chưa có UI — sẽ thêm sau)
Lưu: localStorage key 'litreview.theme'
```

---

## Verification Checklist

### Visual QA (sau mỗi Phase)
- [ ] Font IBM Plex Sans render đúng (không phải Inter)
- [ ] Background: giấy ngà `#f4f1ea` toàn trang
- [ ] Sidebar: `#172238` background, active = coral inset shadow
- [ ] Button primary: ink bg + coral offset shadow (không gradient)
- [ ] Avatar: coral, border-radius 2px (không oval gradient)
- [ ] Topbar: solid paper-bright (không blur glass)
- [ ] Tất cả radius ≤ 4px
- [ ] Focus ring: coral/teal (không xanh navy)
- [ ] Nút [VI][EN] hoạt động, switch không reload
- [ ] Mobile responsive: sidebar ẩn, layout 1 cột

### Regression (logic không bị vỡ)
- [ ] Clerk auth hoạt động
- [ ] Tạo project → API POST thành công
- [ ] Chạy agent → polling status đúng
- [ ] Xem report → data render đúng
- [ ] Reviewer workflow hoạt động

---

## Thứ tự ưu tiên

| Độ ưu tiên | Phase | Lý do |
|---|---|---|
| 🔴 Trước tiên | Phase 0: Setup CSS + i18n | Nền móng, fix m6, m7 |
| 🔴 Trước tiên | Phase 1: Landing page | Fix C4, có nút VI/EN |
| 🔴 Trước tiên | Phase 3: Dashboard | Fix C1–C3, M1–M4, màn hình chính |
| 🟡 Tiếp theo | Phase 5: Project workspace | Core workflow |
| 🟡 Tiếp theo | Phase 2: Auth | Fix M5, m8 |
| 🟡 Tiếp theo | Phase 6: Loading | Fix M6 |
| 🟢 Sau cùng | Phase 7: Report | |
| 🟢 Sau cùng | Phase 4: Create project | Form đơn giản |
