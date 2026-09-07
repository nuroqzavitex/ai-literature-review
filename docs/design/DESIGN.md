---
name: LitReview
description: Bàn nghiên cứu biên tập, có căn cứ và kiểm duyệt rõ ràng.
colors:
  ink: "#172238"
  paper: "#f4f1ea"
  paper-bright: "#fffdf8"
  rule: "#d7d1c6"
  coral: "#d04f35"
  coral-text: "#b83f22"
  green: "#2f7653"
  amber: "#b86a2f"
  blue: "#315fa8"
  muted: "#5d574f"
typography:
  display:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "clamp(3.625rem, 8vw, 6rem)"
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: "-0.035em"
  headline:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "clamp(1.875rem, 3.1vw, 2.875rem)"
    fontWeight: 600
    lineHeight: 1.08
    letterSpacing: "-0.03em"
  body:
    fontFamily: "IBM Plex Sans, ui-sans-serif, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.6
  editorial:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "1.125rem"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "0.625rem"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "0.08em"
rounded:
  editorial: "2px"
  control: "7px"
spacing:
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper-bright}"
    rounded: "{rounded.editorial}"
    padding: "9px 14px"
    height: "44px"
  button-secondary:
    backgroundColor: "{colors.paper-bright}"
    textColor: "{colors.ink}"
    rounded: "{rounded.editorial}"
    padding: "9px 14px"
    height: "44px"
  status-tag:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.muted}"
    typography: "{typography.label}"
    rounded: "{rounded.editorial}"
    padding: "2px 7px"
---

# Design System: LitReview

## Overview

**Creative North Star: "Bàn biên tập nghiên cứu"**

LitReview dùng ngôn ngữ của một ấn phẩm nghiên cứu đang được làm việc trực tiếp: nền giấy ấm, mực xanh đen, rule mảnh và typography phân vai rõ ràng giữa nội dung biên tập, thao tác và metadata. Giao diện có mật độ vừa phải, ưu tiên đọc dài và kiểm tra trạng thái hơn trang trí.

Các bề mặt vận hành dùng cấu trúc ledger, sheet và cột bằng đường phân cách thay vì xếp mọi thứ thành card. Coral đánh dấu hành động có chủ đích; green, amber và blue chỉ xuất hiện khi chúng mang nghĩa trạng thái.

**Key Characteristics:**

- Giấy ấm và mực đậm tạo nền đọc dài ổn định.
- Serif dành cho nhan đề và diễn giải; sans cho thao tác; mono cho hash, ID và trạng thái đo lường.
- Rule mảnh và thay đổi sắc độ tạo cấu trúc; elevation chỉ dành cho lớp nổi thật sự.
- Control vuông nhẹ, nhãn hành động rõ và target tương tác tối thiểu 44px.

## Colors

Palette hạn chế, lấy paper và ink làm diện tích chính; màu ngữ nghĩa xuất hiện có lý do và không thay thế nhãn chữ.

### Primary

- **Mực nghiên cứu**: chữ chính, nút primary và đường phân chia mạnh.
- **Coral biên tập**: điểm active, focus và hành động cần chú ý; chữ nhỏ dùng biến thể coral-text để giữ tương phản.

### Secondary

- **Green xác nhận**: trạng thái hợp lệ, đã kiểm chứng hoặc đã niêm phong.
- **Blue tiến trình**: trạng thái đang chạy, đang review hoặc đang được xử lý.
- **Amber thận trọng**: cảnh báo, thiếu dữ kiện và trạng thái cần bổ sung.

### Neutral

- **Giấy nền**: nền ứng dụng và vùng làm việc phụ.
- **Giấy sáng**: workpaper, form và vùng đọc chính.
- **Rule**: divider và border mặc định.
- **Muted**: nội dung phụ, mô tả và metadata không chủ đạo.

**The Meaningful Color Rule.** Màu trạng thái luôn đi cùng nhãn chữ; không dùng màu làm tín hiệu duy nhất.

## Typography

**Display Font:** Source Serif 4 (với Georgia fallback)  
**Body Font:** IBM Plex Sans (với ui-sans-serif fallback)  
**Label/Mono Font:** IBM Plex Mono (với ui-monospace fallback)

**Character:** Serif tạo nhịp đọc biên tập và trọng lượng học thuật; Plex Sans giữ thao tác gọn; Plex Mono chỉ dành cho dữ liệu có cấu trúc như hash, phiên bản, trạng thái và locator.

### Hierarchy

- **Display** (600, tối đa 6rem, line-height 1.05): nhan đề cấp sản phẩm hoặc bề mặt lớn.
- **Headline** (600, 1.875–2.875rem, line-height 1.08): nhan đề workpaper và nội dung chính.
- **Title** (600, 1–1.5rem): tiêu đề section và nhóm công việc.
- **Body** (500, 0.875rem, line-height 1.6): thao tác và nội dung UI; văn bản dài giữ độ rộng khoảng 65–75 ký tự.
- **Editorial** (400, 1.125rem, line-height 1.65): rationale, diễn giải và nội dung cần đọc chậm.
- **Label** (500–700, 0.625rem): metadata và nhãn trạng thái, thường viết hoa khi độ dài ngắn.

**The Three Voices Rule.** Không dùng mono để tạo cảm giác kỹ thuật; chỉ dùng khi nội dung thực sự là mã, định danh hoặc số đo.

## Layout

Bề mặt lớn dùng grid cột không đối xứng: rail điều khiển hẹp và workpaper rộng, hoặc workpaper cùng cột assessment. Spacing cơ sở theo nhịp 8/12/16/24/32px; khoảng cách giữa section lớn hơn khoảng cách bên trong nhóm. Ở màn hình dưới 800px, rail chuyển lên trên và nội dung thành một cột; dưới 560px, tab rút về icon, action bar xếp dọc và form về một cột.

**The Workpaper Rule.** Nội dung dài nằm trên paper-bright và được chia bằng rule; card chỉ dùng khi một object thực sự cần ranh giới độc lập.

## Elevation & Depth

Hệ thống chủ yếu phẳng và phân lớp bằng tonal surface cùng divider. Shadow mềm chỉ dùng cho toast, modal và surface nổi khỏi document flow; không dùng shadow như viền trang trí cho mọi container.

### Shadow Vocabulary

- **Ambient workpaper** (`0 20px 44px rgba(23,34,56,.07)`): form hoặc gate nổi tạm thời trên nền giấy.
- **Protected modal** (`0 25px 70px rgba(0,0,0,.22)`): tác vụ review cần giữ focus.
- **Transient notice** (`0 14px 38px rgba(23,34,56,.14)`): thông báo có thể đóng.

**The Flat-By-Default Rule.** Một surface ở trạng thái nghỉ không dùng đồng thời border và shadow để tạo “ghost card”.

## Shapes

Control chính dùng góc biên tập gần vuông (2px). Một số control legacy dùng 7px, nhưng bề mặt nghiên cứu mới ưu tiên cạnh thẳng và rule. Pill chỉ dành cho marker tròn, node hoặc status rất ngắn; không dùng pill làm container nội dung.

## Components

### Buttons

- **Shape:** cạnh gần vuông (2px), target tối thiểu 44px.
- **Primary:** nền ink, chữ paper-bright, icon SVG nét 1.7px khi cần.
- **Hover / Focus:** đổi sắc độ nhẹ, dịch lên tối đa 1px; focus ring coral rõ và không phụ thuộc hover.
- **Secondary:** giấy sáng, border ink hoặc rule tùy mức ưu tiên.

### Chips

- **Style:** status tag có border 1px, label mono 10px và cả chữ lẫn màu ngữ nghĩa.
- **State:** green xác nhận, blue tiến trình, amber cần chú ý, coral/đỏ cho từ chối hoặc lỗi.

### Cards / Containers

- **Corner Style:** workpaper và ledger không bo; container độc lập tối đa 7px.
- **Background:** paper hoặc paper-bright.
- **Shadow Strategy:** phẳng mặc định; shadow chỉ cho lớp nổi thật.
- **Border:** rule 1px, hoặc đường ink mạnh ở đầu một section quan trọng.
- **Internal Padding:** thường 16–32px theo mật độ.

### Inputs / Fields

- **Style:** nền trắng, border rule 1px, góc 2px, chữ sans 12–13px.
- **Focus:** border ink cùng outline coral trong suốt; không làm layout dịch chuyển.
- **Error / Disabled:** chữ giải thích cụ thể; disabled giảm opacity nhưng vẫn đọc được nhãn.

### Navigation

Header sản phẩm sticky dùng nền paper-bright và rule dưới. Tab cấp bề mặt chiếm toàn chiều ngang, trạng thái active đổi nền giấy và có đường coral dưới; trên mobile chỉ giữ icon với accessible name đầy đủ.

### Workpaper Timeline

Timeline dùng node, rule và nhãn trạng thái thật từ status history; không tự tạo transition ở frontend. Trên chiều ngang hẹp, timeline cuộn thay vì ép chữ xuống không đọc được.

## Do's and Don'ts

### Do:

- **Do** đặt action ngay cạnh object và trạng thái mà action sẽ thay đổi.
- **Do** hiển thị hash, version, citation và correlation ID bằng mono ở kích thước đọc được.
- **Do** dùng SVG cùng stroke weight cho icon và giữ nhãn chữ cho action quan trọng.
- **Do** làm rõ loading, empty, disabled, error và terminal states.

### Don't:

- **Don't** biến toàn trang thành lưới card cùng kích thước.
- **Don't** dùng màu, icon hoặc animation thay cho tên trạng thái.
- **Don't** dùng gradient text, glass trang trí hoặc texture không thuộc ngôn ngữ giấy biên tập.
- **Don't** dùng raw table rows làm copy minh họa hay đưa chúng vào surface AI prompt.

