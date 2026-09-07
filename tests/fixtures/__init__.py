"""Test fixtures — Mock data dùng chung cho toàn team.

Mục tiêu:
- Cho phép tất cả thành viên test code offline mà không cần gọi OpenAlex API.
- Khi Member 2 hoàn thành OpenAlex Tool thật, thay thế mock này bằng kết quả thật.

Cách dùng trong test:
    from tests.fixtures.mock_papers import MOCK_PAPERS, MOCK_PAPERS_RANKED
"""
