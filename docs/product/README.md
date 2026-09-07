# Product documentation index

Tài liệu trong thư mục này gồm product description hiện tại và artifact Gate/MVP cũ. Trạng thái kỹ thuật hiện hành phải đối chiếu thêm với [kiến trúc hệ thống](../architecture/ARCHITECTURE.md).

## Tài liệu đang duy trì

1. [Brief](Brief.md) — vấn đề, giải pháp và phạm vi hiện tại.
2. [PRD](PRD.md) — requirement và acceptance criteria.
3. [Wireframe & UI Flow](Wireframe_UI_Flow.md) — route và luồng màn hình hiện tại.
4. [GitHub Repo Setup](GitHub_Repo_Setup.md) — setup, checks và release hygiene.
5. [Supabase + Clerk Setup](Supabase_Clerk_Setup.md) — database/auth/collaboration.
6. [Product overview](PRODUCT.md) và [project vision](README_project.md).

## Artifact lịch sử

`gate1.md`, `MVP2_Implementation.md`, `PAPERPULSE_AGENT_ADOPTION_PLAN.md`, `AI_Log.md` và các bản wireframe/analysis khác ghi lại quyết định theo thời điểm. Chúng không tự động là source of truth cho runtime hiện tại.

## Phạm vi hiện tại

Sản phẩm có project workspace, literature-review workflow đa nguồn,
evidence/grounding, research-gap verification, reviewer invitation/API,
Copilot/memory/action proposals, document review và research sandbox. Final
reviewer gate chưa được graph cưỡng chế. PostgreSQL lưu dữ liệu và checkpoint;
Redis/Qdrant là hạ tầng hỗ trợ.
