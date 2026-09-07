# MVP2 Test Traceability Matrix

> Cập nhật cùng PR theo yêu cầu contract §13.1.
> Status=pass chỉ được điền từ CI của commit phát hành.

| Contract requirement | Test ID | Test file | Fixture | Owner | CI evidence | Status |
|---|---|---|---|---|---|---|
| §5.A Session hợp lệ resolve đúng actor | AUTH-001 | tests/v2/api/test_auth_project.py | actor_matrix | — | — | scaffold |
| §5.A Session revoked/expired bị từ chối | AUTH-002 | tests/v2/api/test_auth_project.py | actor_matrix | — | — | scaffold |
| §5.A Bootstrap chỉ hoạt động ở test/local | AUTH-003 | tests/v2/api/test_auth_project.py | — | — | — | scaffold |
| §5.A V2 request có identity field trả 422 | AUTH-004 | tests/v2/api/test_auth_project.py | — | — | — | scaffold |
| §5.A Outsider không đọc project data | AUTH-005 | tests/v2/api/test_auth_project.py | actor_matrix | — | — | scaffold |
| §5.A Legacy V1 field không cấp quyền V2 | AUTH-006 | tests/v2/api/test_auth_project.py | actor_matrix | — | — | scaffold |
| §5.H IDOR cross-project blocked | SEC-001 | tests/v2/api/test_auth_project.py | actor_matrix | — | — | scaffold |
| §5.H Session token not in response body | SEC-003 | tests/v2/api/test_auth_project.py | — | — | — | scaffold |
| §5.B CapabilitySnapshot returned per turn | CHAT-001 | tests/v2/api/test_conversations.py | — | — | — | scaffold |
| §5.B Stage empty limits factual answers | CHAT-002 | tests/v2/api/test_conversations.py | — | — | — | scaffold |
| §5.B Conversation creation project-bound | CHAT-003 | tests/v2/api/test_conversations.py | — | — | — | scaffold |
| §5.B Idempotent message (same client_msg_id) | CHAT-007 | tests/v2/api/test_conversations.py | — | — | — | scaffold |
| §5.B Stale expected_report_version_id → 409 | CHAT-008 | tests/v2/api/test_conversations.py | — | — | — | scaffold |
| §5.E Unknown action_type rejected 422 | ACT-003 | tests/v2/integration/test_action_execution.py | — | — | — | scaffold |
| §5.E Unconfirmed mutation — executor calls = 0 | ACT-004 | tests/v2/integration/test_action_execution.py | — | — | — | scaffold |
| §5.E Same key different payload → 409 | ACT-007 | tests/v2/integration/test_action_execution.py | — | — | — | scaffold |
| §5.E Version Service not callable as LLM tool | ACT-012 | tests/v2/integration/test_action_execution.py | — | — | — | scaffold |
| §5.I V1 suite tiếp tục pass | REG-001 | tests/v2/integration/test_v1_migration.py | — | — | — | scaffold |
| §5.I V1 endpoint giữ response behavior | REG-002 | tests/v2/integration/test_v1_migration.py | — | — | — | scaffold |
| §5.I Migration additive đọc V1 report | REG-003 | tests/v2/integration/test_v1_migration.py | — | — | — | scaffold |
| §5.I Roll-forward migration idempotent | REG-004 | tests/v2/integration/test_v1_migration.py | — | — | — | scaffold |
| §6 AS-01 Grounded Q&A capabilities snapshot | AS-01 | tests/v2/e2e/test_acceptance_scenarios.py | — | — | — | scaffold |
| §6 AS-02 Insufficient evidence stage=empty | AS-02 | tests/v2/e2e/test_acceptance_scenarios.py | — | — | — | scaffold |
| §6 AS-03 Cross-project IDOR blocked | AS-03 | tests/v2/e2e/test_acceptance_scenarios.py | — | — | — | scaffold |
| §6 AS-05 Search refinement action creation | AS-05 | tests/v2/e2e/test_acceptance_scenarios.py | — | — | — | scaffold |
| §6 AS-06 Idempotency key same action | AS-06 | tests/v2/e2e/test_acceptance_scenarios.py | — | — | — | scaffold |
| §6 AS-07 Stale base version → ACTION_STALE | AS-07 | tests/v2/e2e/test_acceptance_scenarios.py | — | — | — | scaffold |
