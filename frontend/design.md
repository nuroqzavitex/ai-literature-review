# LitReview — Design Contract

> **Foundation thị giác chung.** Mọi model phải đọc file này trước khi tạo hoặc chỉnh sửa bất kỳ màn hình nào của LitReview. Token chung và nguyên tắc semantic ở đây áp dụng toàn app; hướng dẫn riêng của từng surface chỉ áp dụng cho surface đó.
>
> **Trạng thái bảng màu và typography**: Đã được người dùng thực tế xác nhận là đẹp và phù hợp. Không thay đổi.

---

## 1. Bảng màu — Color Tokens

Nguồn gốc từ `mock-base.css` và `mock-polish.css` trong frontend.

```css
:root {
  /* === BỀ MẶT / SURFACES === */
  --paper:        #f4f1ea;   /* Nền trang chính — ivory ấm như giấy in */
  --paper-bright: #fffdf8;   /* Nền artifact, card, sidebar sáng */
  --paper-deep:   #e9e3d8;   /* Nền trũng, shadow offset, footer band */
  --paper-wash:   #faf7f0;   /* Nền hover state nhẹ */

  /* === INK / CHỮ === */
  --ink:          #172238;   /* Navy đậm — màu chữ chính, border chính */
  --ink-soft:     #293852;   /* Ink nhạt hơn — dùng trong dark section */

  /* === THANG XÁM / GRAY SCALE === */
  --g50:          #f4f1ea;
  --g100:         #ece8df;
  --g200:         #ddd8ce;
  --g300:         #c9c2b6;
  --g400:         #a49c90;   /* Icon xám, số thứ tự phụ */
  --g500:         #756e65;   /* Metadata phụ, folio, placeholder */
  --g600:         #5d574f;   /* Body text phụ, mô tả ngắn */
  --g700:         #3e3a35;
  --g800:         #292825;
  --g900:         #171a1f;

  /* === MÀU NGHĨA / SEMANTIC COLORS === */
  --coral:        #d04f35;   /* Màu nhấn chính — CTA, eyebrow, conflict, accent */
  --coral-wash:   #f7e8e2;   /* Nền coral nhạt — live label, hover tint */
  --teal:         #274c9b;   /* Blue research — node, link, data */
  --teal-d:       #18366f;   /* Teal đậm */
  --teal-soft:    #e8edf7;   /* Nền teal nhạt */
  --teal-mid:     #aab9d8;   /* Metadata teal, secondary */
  --green:        #2f7653;   /* Supported / grounded — score xanh */
  --amber:        #b86a2f;   /* Cảnh báo, uncertain state */
  --blue:         #315fa8;   /* Link màu khác với coral */
  --purple:       #6f5687;   /* Secondary accent, tag */

  /* === ĐƯỜNG KẺ / BORDERS === */
  --rule:         #d7d1c6;   /* Hairline border chính */
}
```

### Ý nghĩa ngữ nghĩa (Semantic Mapping)

| Ý nghĩa | Token | Dùng khi nào |
|---|---|---|
| Nhấn chính / action | `--coral` | CTA, eyebrow, conflict, số step, left-border accent |
| Chữ chính / text | `--ink` | Heading, nav, body text đậm |
| Nền trang | `--paper` | Background toàn trang |
| Nền artifact | `--paper-bright` | Card, dossier, sidebar |
| Nền trũng | `--paper-deep` | Shadow offset (box-shadow), footer band |
| Metadata phụ | `--g500` | Folio, monospace label, date |
| Body phụ | `--g600` | Mô tả ngắn, paragraph trong dark section |
| Grounded / supported | `--green` | Score ≥ 0.8, evidence supported |
| Uncertain / warning | `--amber` | Pending state, cảnh báo |
| Research data | `--teal` | Node, link, coverage number |
| Border chuẩn | `--rule` | Hairline giữa các row, card border |

### Màu KHÔNG được dùng

- ❌ Gradient tím/xanh neon toàn màn hình
- ❌ Glass card với `backdrop-filter: blur`
- ❌ `--coral` cho trạng thái supported/safe (chỉ dùng cho accent và conflict)
- ❌ Màu bất kỳ không có trong danh sách token trên

---

## 2. Typography — Kiểu chữ

### Font family

```css
/* Đã import trong app/layout.tsx — KHÔNG thêm font khác */
--font-serif: "Source Serif 4", Georgia, serif;
--font-sans:  "IBM Plex Sans", ui-sans-serif, sans-serif;
--font-mono:  "IBM Plex Mono", ui-monospace, monospace;
```

| Vai trò | Font | Trọng số | Dùng cho |
|---|---|---:|---|
| Display / Hero | Source Serif 4 | 600–700 | H1, CTA heading, câu hỏi lớn |
| Section heading | Source Serif 4 | 600 | H2, H3, tên paper / claim |
| Body UI | IBM Plex Sans | 400–600 | Nav, button, paragraph, form, menu |
| Research metadata | IBM Plex Mono | 400–500 | ID, score, tag, ngày, trạng thái, API-like data |

### Scale typography theo surface

Chỉ font aliases dưới đây là token global. Các type scale được định nghĩa gần surface đang dùng; landing hiện dùng `--t-display`, `--t-h2-lg`, `--t-h2-sm`, `--t-h3`, `--t-body`, `--t-body-sm`, `--t-body-serif`, `--t-mono-label`, `--t-mono-meta` và `--t-source-title` trong `mock-landing.css`.

```css
/* Landing surface — currently implemented */
--t-display:      600 clamp(58px, 8vw, 104px) / 1.05 var(--font-serif);
--t-h2-lg:        600 clamp(36px, 4.8vw, 58px) / 1.04 var(--font-serif);
--t-h2-sm:        600 30px / 1.1 var(--font-serif);
--t-h3:           600 20px / 1.15 var(--font-serif);
--t-editorial:        18px / 1.65 var(--font-serif);
--t-body:         500 14px / 1.6 var(--font-sans);
--t-body-sm:          13px / 1.65 var(--font-sans);
--t-body-serif:       15px / 1.6 var(--font-serif);
--t-mono-label:  700 10px / 1 var(--font-mono);
--t-mono-meta:   400 10px / 1 var(--font-mono);
--t-source-title:    15px / 1.3 var(--font-serif);
```

### Quy tắc typography bắt buộc

1. Chỉ `Source Serif 4` cho heading; không dùng font serif khác.
2. Label kỹ thuật phải dùng `IBM Plex Mono`, uppercase, letter-spacing `.08em`–`.12em`.
3. Body text không quá `--g600`; heading luôn `--ink`.
4. Hero title không quá 3 dòng desktop, 4 dòng mobile.
5. Không dùng italic cho body; italic chỉ dành cho trích dẫn evidence.
6. Không dùng font-weight dưới 400 hoặc trên 700.

---

## 3. Layout System — Không gian và Grid

### Container

```css
--content-wide: 1180px;  /* Landing, dashboard chính */
--content-mid:   960px;  /* FAQ, report */
--content-narrow:760px; /* Article, synthesis text */
--page-gutter: clamp(24px, calc((100vw - 1180px) / 2), 96px);
```

```css
.container-wide   { padding-inline:max(24px, calc((100vw - 1180px) / 2)); }
.container-mid    { padding-inline:max(24px, calc((100vw -  960px) / 2)); }
.container-narrow { padding-inline:max(24px, calc((100vw -  760px) / 2)); }
```

### Spacing scale

| Token | Giá trị | Dùng cho |
|---|---:|---|
| `--sp-1` | 4px | Gần sát: icon–label |
| `--sp-2` | 8px | Row internal gap |
| `--sp-3` | 12px | Card internal spacing |
| `--sp-4` | 16px | Form field gap |
| `--sp-5` | 24px | Card padding nhỏ |
| `--sp-6` | 32px | Card padding / section grid gap |
| `--sp-7` | 48px | Heading → body gap |
| `--sp-8` | 64px | Section heading → content |
| `--sp-9` | 96px | Section padding desktop |
| `--sp-10` | 120px | Hero / major section padding |

### Page rhythm

- Landing desktop: section padding dọc `108px`–`148px`.
- Landing mobile: section padding dọc `72px`–`96px`.
- App shell: header `68px`; sidebar `260px`–`280px`.
- Artifact card: padding `24px`–`34px`.
- Trên landing, ưu tiên ledger/list thay vì lưới card lặp lại. Trong workspace, report và modal, nested card được phép khi nó thể hiện một object có scope độc lập (claim, evidence, form, decision); không bọc card chỉ để thêm trang trí.

### Breakpoints

```css
/* 960px: tablet / laptop nhỏ — collapse navigation & 4-col grids */
@media (max-width: 960px) { }

/* 600px: mobile — single column, touch-friendly controls */
@media (max-width: 600px) { }
```

---

## 4. Surface & Material — Cảm giác vật liệu

### Nguyên tắc chung

LitReview mang cảm giác **research desk / editorial paper / technical dossier**. Không phải SaaS bóng bẩy, không phải neon AI dashboard.

- Bề mặt chính là ivory ấm (`--paper`), không trắng tuyệt đối.
- Dossier / artifact là `--paper-bright`, có border 1px `--rule`.
- Các nhóm nội dung lớn có thể xen kẽ giữa `--paper`, `--paper-bright` và `--paper-deep` khi điều đó giúp phân biệt ngữ cảnh.
- `--landing-warm` (`#eee9df`) và `--landing-cool` (`#edf2ed`) là local token của `ProductLanding`; không gọi từ dashboard, workspace, auth hay report. Khi một surface khác thực sự cần tone riêng, khai báo local token có tên theo surface đó.
- Border là hairline 1px, không dùng bo tròn quá lớn.
- Landing và artifact editorial ưu tiên góc vuông hoặc `2px`–`4px`. Product UI có thể dùng `6px`–`14px` cho control, modal, composer và vùng tương tác dày đặc khi điều đó làm thao tác rõ ràng hơn. Không dùng pill cho card nội dung; pill chỉ dành cho tag, avatar hoặc compact status.
- Shadow có offset nhỏ và blur mềm: `0 14px 34px rgba(23,34,56,.08)`. Không dùng shadow màu rực.
- Có thể dùng texture paper/noise `opacity <= .03` trên toàn trang.

### Dossier / Paper card

```css
.artifact-paper {
  background: var(--paper-bright);
  border: 1px solid var(--rule);
  box-shadow: 0 14px 34px rgba(23,34,56,.08), 0 2px 5px rgba(23,34,56,.05);
  padding: 32px;
}
```

### Nội dung có trạng thái

| Trạng thái | Màu | Ví dụ |
|---|---|---|
| Supported / grounded | `--green` | Evidence strength ≥ 0.8, cited source |
| Review / pending | `--amber` | Needs human review |
| Conflict | `--coral` | Hai nguồn mâu thuẫn |
| Data / linked | `--teal` | Knowledge graph, source link |
| Neutral metadata | `--g500` | Paper ID, ngày, author |

---

## 5. Components — Quy tắc component

### Button

```css
.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 10px 18px;
  border: 1px solid var(--ink);
  border-radius: 2px;
  background: var(--ink);
  color: #fff;
  font: 600 13px var(--font-sans);
  box-shadow: 3px 3px 0 var(--coral);
}

.btn-secondary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 10px 18px;
  border: 1px solid var(--rule);
  border-radius: 2px;
  background: var(--paper-bright);
  color: var(--ink);
  font: 600 13px var(--font-sans);
}
```

- CTA chính: navy + coral offset shadow.
- CTA phụ: nền sáng, border hairline.
- Hover primary: translate `-1px -1px`, shadow `4px 4px 0 var(--coral)`.
- Không dùng gradient button, pill button, hoặc button lớn không có action rõ.

### Data row / ledger row

```css
.ledger-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 16px;
  align-items: start;
  border-top: 1px solid var(--rule);
  padding: 16px 0;
}
```

- Ưu tiên row có đường kẻ hơn card cho danh sách paper, claim, evidence.
- Metadata đặt dưới title; score/trạng thái căn phải.
- Hover row dùng `--paper-wash`, không đổi toàn bộ màu chữ.

### Nav / Header

- Landing header sticky, cao `68px`, background ivory mờ nhẹ (`color-mix`).
- Full-bleed theo viewport; nội dung trong header canh theo `--content-wide`.
- Nav link 13px IBM Plex Sans, active underline coral 2px.
- Mobile ẩn nav chữ; giữ logo + CTA chính.
- Header không được có margin mặc định quanh viewport.

### Form

- Input background `--paper-bright`, border `--rule`, radius `2px`–`4px`.
- Focus: `outline: 2px solid var(--coral); outline-offset: 3px`.
- Label dùng sans 12px–13px, không dùng uppercase trừ label metadata kỹ thuật.
- Helper/error text nằm sát input, không dùng toast cho lỗi validation đơn giản.

---

## 6. Motion — Chuyển động có mục đích

### Timing

```css
--ease-out: cubic-bezier(.16, 1, .3, 1);
--duration-fast: 160ms;
--duration-base: 240ms;
--duration-slow: 520ms;
```

### Được dùng

- Section reveal: `opacity + translateY(18px)` khi vào viewport, stagger 80ms.
- Dossier content: từng row xuất hiện tuần tự, delay 80ms–120ms.
- Interactive demo: scene đổi bằng `opacity + translateY(10px) + clip-path` trong 420ms.
- Hover artifact/card: `translateY(-3px)` tối đa, shadow tăng nhẹ.
- Logo mark: `translateY(-2px) rotate(-2deg)` khi hover.
- Accordion: grid-row transition hoặc height transition, tối đa 320ms.

### Không được dùng

- Parallax mạnh theo chuột.
- Auto-rotating card/carousel.
- Loop animation liên tục trên text.
- Bounce, elastic, hoặc spring quá đà.
- Animation chỉ để “trông AI hơn”.

### Accessibility

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .01ms !important;
    scroll-behavior: auto !important;
  }
}
```

---

## 7. Landing Page — Hướng dẫn riêng cho surface Marketing

Áp dụng cho `/` và các marketing landing trong tương lai; không áp dụng cho dashboard, workspace, report hay auth. Landing hiện tại đã triển khai theo reading order này:

1. **Header** — logo, 2–3 nav links, language toggle, CTA.
2. **Hero** — 55% narrative trái, 45% evidence trail phải. Hero giải thích luồng `Question → Source → Claim → Conflict → Gap`; không dùng card bay chỉ để trang trí.
3. **Dossier preview** — một research question + source ledger, cho thấy artifact thực.
4. **Interactive demo** — tab Brief → Sources → Evidence; người dùng nhìn thấy sản phẩm vận hành.
5. **Capabilities** — ledger/list 3–6 khả năng; không dùng lưới card giống nhau.
6. **Workflow** — 3–4 bước, mỗi bước có output artifact.
7. **Trust / principles** — nền navy, giải thích vì sao evidence đáng tin.
8. **FAQ** — 3–5 câu hỏi, accordion.
9. **CTA cuối** — một hành động chính, copy ngắn.
10. **Footer** — brand statement, product links, legal/contact.

### Hero evidence trail

```text
Question
  ↓
Source / S012
  ↓
Claim / C018
  ↓
Conflict / E037
  ↓
Gap / G03
```

- Card trong trail là ví dụ trực tiếp sản phẩm suy luận, không phải decoration.
- Narrative và evidence trail phải đồng cấp về visual weight.
- Trên mobile, narrative trước rồi trail theo DOM order.

---

## 8. Accessibility & UX Checklist

- [ ] Body text có contrast ít nhất 4.5:1.
- [ ] Mọi button/link có `:focus-visible` rõ.
- [ ] Target chạm tối thiểu 42px cao.
- [ ] Không chỉ dùng màu để truyền đạt trạng thái; score/status có text.
- [ ] Icon có `aria-hidden` nếu decorative; action icon có `aria-label`.
- [ ] Heading hierarchy không nhảy cấp.
- [ ] Các anchor section có `scroll-margin-top` để không bị sticky header che.
- [ ] Mobile không có horizontal overflow ở 320px.
- [ ] `prefers-reduced-motion` được tôn trọng.
- [ ] CTA nói rõ action thực hiện, không dùng “Click here”.

---

## 9. Quy trình khi tạo/chỉnh sửa UI

1. Đọc `frontend/design.md` trước.
2. Tìm component và stylesheet liên quan; không sửa CSS global nếu chỉ một page cần thay đổi.
3. Dùng global token có sẵn. Nếu cần token local cho một surface, đặt tên theo surface và ghi phạm vi sử dụng cạnh nơi khai báo; chỉ thêm token global khi nó có ít nhất hai surface dùng chung.
4. Giữ thiết kế paper/editorial/research-desk; không chuyển sang SaaS gradient hoặc glassmorphism.
5. Kiểm tra desktop (>= 1180px), tablet (960px), mobile (<= 600px).
6. Chạy `npm run lint` trong `frontend/` sau thay đổi TypeScript.
7. Nếu thay đổi UI, chạy Impeccable detector trên file thay đổi.

---

## 10. Ví dụ anti-pattern

| Không làm | Thay bằng |
|---|---|
| 6 card feature giống nhau | Ledger/list có index, title, mô tả, output |
| Hero có nhiều floating card decoration | Evidence trail có quan hệ Question → Evidence → Gap |
| Gradient purple/blue AI | Paper + ink + coral semantic accent |
| Glassmorphism / blur card | Paper artifact có border + shadow nhẹ |
| Nhiều pill/badge màu | Mono metadata label, border hairline |
| Animation loop trên text | Reveal / state-change một lần có mục đích |
| Một file CSS chung cho mọi màn | Style theo screen/component, token global tối thiểu |

---

_Cập nhật lần cuối: 2026-08-14. Mọi thay đổi thị giác phải cập nhật Design Contract này trước hoặc cùng lúc với code._
