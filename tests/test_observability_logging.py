from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from types import SimpleNamespace

from src import logging_utils
from src.agents.litreview.application.jobs import _paper_progress_counts
from src.logging_utils import event, id_summary, paper_summary


def test_structured_event_is_json_searchable_and_bounded(caplog):
    caplog.set_level(logging.INFO, logger="tests.observability")
    event(
        logging.getLogger("tests.observability"),
        "screen.embedding_gate",
        state={"job_id": "job-1", "run_id": "run-1", "execution_mode": "review"},
        passed_count=2,
    )

    line = caplog.records[-1].message
    payload = json.loads(line[line.index("{") :])
    assert payload["event"] == "screen.embedding_gate"
    assert payload["job_id"] == "job-1"
    assert payload["run_id"] == "run-1"
    assert payload["passed_count"] == 2


def test_structured_event_redacts_secrets_and_user_content(caplog):
    caplog.set_level(logging.INFO, logger="tests.observability")
    event(
        logging.getLogger("tests.observability"),
        "job.failed",
        api_key="should-not-appear",
        resume_payload={"review_feedback": "private"},
        error="provider response body",
    )
    payload = json.loads(caplog.records[-1].message.split(" ", 1)[1])
    assert payload["api_key"] == "[REDACTED]"
    assert payload["resume_payload"]["redacted"] is True
    assert payload["error"]["redacted"] is True


def test_sampling_keeps_warning_events_and_can_drop_info(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="tests.observability")
    monkeypatch.setattr(
        logging_utils,
        "get_settings",
        lambda: SimpleNamespace(observability_event_sample_rate=0.0),
    )
    test_logger = logging.getLogger("tests.observability")
    event(test_logger, "job.node_completed", state={"job_id": "job-sampled"})
    event(test_logger, "job.failed", state={"job_id": "job-sampled"}, level=logging.ERROR)
    assert [record.message.split(" ", 1)[0] for record in caplog.records] == ["event=job.failed"]


def test_summaries_keep_identifiers_bounded_and_omit_full_text():
    summary = paper_summary(
        {
            "paper_id": "paper-1",
            "title": "A paper",
            "abstract": "private full text",
            "relevance_score": 0.9,
            "relevance_reason": "Direct evidence",
        }
    )
    assert "relevance_reason" not in summary
    assert "abstract" not in summary
    assert id_summary(["a", "b"])["count"] == 2


def test_empty_paper_update_resets_progress_instead_of_reusing_stale_total():
    assert _paper_progress_counts({"papers": []}, 12) == (0, 0)
    assert _paper_progress_counts({"current_node": "compose"}, 12) == (12, 12)


def test_python_rotating_tee_caps_file_and_preserves_stdout(tmp_path):
    target = tmp_path / "worker.log"
    result = subprocess.run(
        [sys.executable, "scripts/rotating_tee.py", str(target), "--max-bytes", "5"],
        input=b"123456789\n",
        capture_output=True,
        check=True,
    )

    assert result.stdout == b"123456789\n"
    assert target.stat().st_size == 5


def test_node_rotating_tee_caps_file_and_preserves_stdout(tmp_path):
    node = shutil.which("node")
    if node is None:
        return
    target = tmp_path / "frontend.log"
    result = subprocess.run(
        [node, "frontend/scripts/rotating-tee.mjs", str(target), "5"],
        input=b"123456789\n",
        capture_output=True,
        check=True,
    )

    assert result.stdout == b"123456789\n"
    assert target.stat().st_size == 5
