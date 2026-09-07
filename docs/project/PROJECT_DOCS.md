# Project Documentation Index

> Trang điều hướng tài liệu đang được duy trì. File này không còn là snapshot ghép của README, worklog và log cũ.

## Bắt đầu

- [README dự án](../../README.md)
- [Product overview](../product/PRODUCT.md)
- [Thiết lập repository](../product/GitHub_Repo_Setup.md)
- [Demo toàn bộ dự án](DEMO_TOAN_BO_DU_AN.md)

## Kiến trúc và thiết kế

- [Kiến trúc hệ thống hiện tại](../architecture/ARCHITECTURE.md)
- [Sơ đồ kiến trúc](../architecture/architecture_diagram.md)
- [Luồng LitReview StateGraph](../architecture/AGENT_STATE_GRAPH.md)
- [Luồng Research Gap](../architecture/RESEARCH_GAP_FLOW.md)
- [System Design](../design/SYSTEM_DESIGN.md)
- [Basic Design](../design/BASIC_DESIGN.md)
- [Detailed Design](../design/DETAILED_DESIGN.md)

## Vận hành

- [Worker runtime](../operations/WORKER_RUNTIME.md)
- [Triển khai Ubuntu VPS](../operations/DEPLOY_UBUNTU_VPS_NATIVE.md)
- [Supabase và Clerk](../product/Supabase_Clerk_Setup.md)

## Contract và API

- [Technical contract index](../reference/README_technical_contract.md)
- [Academic search và ingestion](../reference/ACADEMIC_SEARCH_AND_INGESTION.md)
- [Contract V1](../../contracts/contract_v1.md), [V2](../../contracts/contract_v2.md), [V3](../../contracts/contract_v3.md), [V4](../../contracts/contract_v4.md)
- OpenAPI runtime: `http://localhost:8000/docs`

## Product và lịch sử

- Tài liệu Gate/MVP trong `docs/product/` và `docs/roadmap/` là artifact theo giai đoạn; trạng thái trong đó không tự động đại diện cho runtime hiện tại.
- [Kế hoạch rebuild frontend lịch sử](../design/FRONTEND_REBUILD_PLAN.md).
- [Handoff nhánh mindmap ngày 2026-08-21](../archive/handoffs/MINDMAP_HANDOFF_2026-08-21.md).
- Concept chưa triển khai nằm trong `docs/roadmap/concepts/`.
- `WORKLOG.md` ở root là nhật ký công việc nhóm.

## Nguồn sự thật

Khi có mâu thuẫn, ưu tiên theo thứ tự: code và migration đang chạy → `src/config.py`/`.env.example`/Docker Compose → tài liệu architecture living → contract/roadmap theo phiên bản → artifact lịch sử.
