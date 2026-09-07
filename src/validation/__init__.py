"""Validation module — Grounding & Citation Verification.

Member 3 làm việc chính tại đây.

Mục tiêu:
- Kiểm tra xem mỗi Claim/Evidence có thực sự xuất hiện trong Abstract không.
- Phát hiện và loại bỏ DOI/URL bịa (không tồn tại trên OpenAlex).
- Reject các khẳng định tuyệt đối không có bằng chứng ("never studied", "no research").

Interface chuẩn để Leader gọi từ Node `summarize_matrix`:
    from src.validation.grounding import validate_summary

Xem grounding.py để biết chi tiết.
"""
