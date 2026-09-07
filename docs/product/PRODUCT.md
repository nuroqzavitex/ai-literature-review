# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- Suy luận từ mã nguồn và yêu cầu: nhà nghiên cứu, reviewer và chủ project cần tìm, kiểm chứng, tổng hợp và thử nghiệm các giả thuyết trên nguồn học thuật trong phạm vi một project.
- Suy luận: người dùng chính làm việc theo quy trình có kiểm soát, cần nhìn rõ trạng thái, bằng chứng, giới hạn và điểm cần phê duyệt trước khi dữ liệu được đưa sang luồng chính.

## Product Purpose

LitReview là bàn nghiên cứu dựa trên bằng chứng. Sản phẩm hỗ trợ tìm, đọc và tổng hợp nghiên cứu; Research Sandbox bổ sung hai không gian thử nghiệm đang được frontend cung cấp: giả thuyết và phân tích dữ liệu có khả năng tái lập.

## Positioning

Các ranh giới tin cậy gồm context bất biến, citation truy vết được, approval gate khi chọn corpus và bundle tái lập; Sandbox không tự sửa base graph hay tự xuất bản vào hệ thống chính. Final reviewer API đã tồn tại, nhưng graph hiện tự hoàn tất sau bước chọn paper nên final reviewer gate chưa được cưỡng chế trong runtime.

## Operating Context

- Người dùng làm việc trong một project và kế thừa quyền thành viên từ backend chính.
- Hai mode Sandbox xuất hiện trên frontend: giả thuyết và phân tích dữ liệu.
- Graph Overlay còn code ở backend/contract cũ nhưng mặc định bị tắt và đã bị gỡ khỏi frontend; không trình bày nó như tính năng người dùng hiện tại.
- Các hành động AI, execution và adoption được thể hiện thành state machine; frontend không tự suy diễn transition bị thiếu.
- Frontend chỉ gọi BFF cùng origin tại `/api/v1/projects/{project_id}/sandbox` và không biết thông tin xác thực giữa dịch vụ hay object-store key.

## Capabilities and Constraints

- Sandbox bị chặn bởi capability/feature flags và có thể tắt hoàn toàn mà không ảnh hưởng luồng lõi.
- Dataset người dùng đưa vào Sandbox được phân loại `non_sensitive`; giới hạn định dạng và dung lượng lấy từ capabilities.
- Raw rows không được đưa vào prompt AI hoặc log; profiling là deterministic.
- Run/review/hand-off cần idempotency key; polling dừng ở terminal state hoặc khi rời màn hình.
- Adoption chỉ tạo draft ở backend chính sau khi reviewer phê duyệt.
- Literature-review graph đang dừng để người dùng duyệt sub-query và paper ở `review` mode. Node final review tự tiếp tục ở cả `review` và `autonomous`; muốn công bố final reviewer gate là hoàn chỉnh phải sửa runtime và test trước.
- Các chi tiết sản phẩm chưa được người dùng xác nhận trực tiếp trong phiên này được đánh dấu là “Suy luận”.

## Brand Commitments

- Tên sản phẩm hiện tại: LitReview.
- Giao diện và nội dung chính dùng tiếng Việt; giữ khả năng chuyển ngôn ngữ hiện có.
- Research Sandbox phải kế thừa visual language biên tập hiện có, không làm thay đổi các màn hình khác.

## Evidence on Hand

- Hợp đồng frontend: `research-sandbox/docs/frontend-contract.md`.
- Backend BFF và allowlist: `src/api/routers/sandbox.py`.
- Design tokens và bề mặt hiện hữu: `frontend/app/styles/` và các component trong `frontend/app/_components/`.
- Không có testimonial, benchmark thương mại hoặc asset khách hàng nào được xác nhận; không được tự tạo các tuyên bố này.

## Product Principles

1. Hiển thị nguồn gốc và giới hạn trước khi tạo cảm giác chắc chắn.
2. Tách thử nghiệm khỏi dữ liệu và graph nền cho tới khi reviewer chủ động thông qua.
3. Mỗi trạng thái quan trọng phải quan sát được, có thể kiểm tra và phục hồi an toàn.
4. AI hỗ trợ tạo bản thảo và diễn giải; code deterministic và reviewer mới quyết định việc chấp nhận.
5. Khi Sandbox tắt hoặc gián đoạn, sản phẩm lõi vẫn hoạt động bình thường.

## Accessibility & Inclusion

Suy luận từ hệ thống hiện có: hỗ trợ bàn phím, focus-visible, reduced motion, nhãn trạng thái không phụ thuộc riêng vào màu và bố cục web đáp ứng từ 320px.
