"""Dependency-light structured telemetry for the control service and worker.

Metrics deliberately contain identifiers and counts only.  Raw prompts, dataset
content, generated code, child logs, and artifact bodies are never accepted as
structured log fields.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import re
from threading import Lock
from typing import Mapping


_METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LABEL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_SAFE_LOG_FIELDS = {
    "artifact_count",
    "correlation_id",
    "duration_ms",
    "error_code",
    "lease_owner",
    "project_id",
    "reason",
    "run_id",
    "status",
    "worker_id",
}
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|password|secret|token)\s*[:=]\s*[^\s,;]+"
)


class SandboxMetrics:
    """Small in-process registry with Prometheus-compatible exposition."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._observations: dict[
            tuple[str, tuple[tuple[str, str], ...]], tuple[int, float]
        ] = {}

    def increment(
        self, name: str, value: float = 1, *, labels: Mapping[str, str] | None = None
    ) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += value

    def set_gauge(
        self, name: str, value: float, *, labels: Mapping[str, str] | None = None
    ) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def observe(
        self, name: str, value: float, *, labels: Mapping[str, str] | None = None
    ) -> None:
        key = self._key(name, labels)
        with self._lock:
            count, total = self._observations.get(key, (0, 0.0))
            self._observations[key] = (count + 1, total + value)

    def snapshot(self) -> dict[str, dict[str, float]]:
        with self._lock:
            counters = {self._display(key): value for key, value in self._counters.items()}
            gauges = {self._display(key): value for key, value in self._gauges.items()}
            observations: dict[str, float] = {}
            for key, (count, total) in self._observations.items():
                display = self._display(key)
                observations[f"{display}_count"] = float(count)
                observations[f"{display}_sum"] = total
        return {"counters": counters, "gauges": gauges, "observations": observations}

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for key, value in sorted(self._counters.items()):
                lines.append(f"{self._render_key(key)} {self._format(value)}")
            for key, value in sorted(self._gauges.items()):
                lines.append(f"{self._render_key(key)} {self._format(value)}")
            for (name, labels), (count, total) in sorted(self._observations.items()):
                lines.append(
                    f"{self._render_key((name + '_count', labels))} {count}"
                )
                lines.append(
                    f"{self._render_key((name + '_sum', labels))} {self._format(total)}"
                )
        return "\n".join(lines) + ("\n" if lines else "")

    @staticmethod
    def _key(
        name: str, labels: Mapping[str, str] | None
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        if not _METRIC_NAME.fullmatch(name):
            raise ValueError("invalid metric name")
        normalized = tuple(sorted((labels or {}).items()))
        for label, value in normalized:
            if not _LABEL_NAME.fullmatch(label):
                raise ValueError("invalid metric label")
            if len(value) > 128 or any(character in value for character in "\r\n"):
                raise ValueError("invalid metric label value")
        return name, normalized

    @staticmethod
    def _format(value: float) -> str:
        return str(int(value)) if float(value).is_integer() else repr(float(value))

    @staticmethod
    def _render_key(key: tuple[str, tuple[tuple[str, str], ...]]) -> str:
        name, labels = key
        if not labels:
            return name
        rendered = ",".join(
            f'{label}="{value.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
            for label, value in labels
        )
        return f"{name}{{{rendered}}}"

    @staticmethod
    def _display(key: tuple[str, tuple[tuple[str, str], ...]]) -> str:
        return SandboxMetrics._render_key(key)


class StructuredEventLogger:
    """Emit one JSON object per event using an explicit non-sensitive field list."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("sandbox.worker")

    def emit(self, event: str, *, level: int = logging.INFO, **fields: object) -> None:
        safe_fields = {
            key: self._sanitize(value)
            for key, value in fields.items()
            if key in _SAFE_LOG_FIELDS and value is not None
        }
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event[:96],
            **safe_fields,
        }
        self._logger.log(level, json.dumps(payload, sort_keys=True, separators=(",", ":")))

    @staticmethod
    def _sanitize(value: object) -> object:
        if isinstance(value, (int, float, bool)):
            return value
        rendered = str(value).replace("\r", " ").replace("\n", " ")[:256]
        return _SECRET_PATTERN.sub(r"\1=<redacted>", rendered)


@dataclass
class WorkerProbeState:
    healthy: bool = True
    ready: bool = False
    accepting_work: bool = True
    active_run_id: str | None = None
    last_poll_at: datetime | None = None
    last_error_code: str | None = None

    def health_payload(self) -> dict[str, object]:
        return {"status": "ok" if self.healthy else "failed"}

    def readiness_payload(self) -> dict[str, object]:
        ready = self.healthy and self.ready and self.accepting_work
        return {
            "status": "ready" if ready else "not_ready",
            "accepting_work": self.accepting_work,
            "active_run": self.active_run_id is not None,
            "last_error_code": self.last_error_code,
        }


class WorkerProbeServer:
    """Minimal HTTP probe server for a separately deployed worker process."""

    def __init__(
        self,
        *,
        state: WorkerProbeState,
        metrics: SandboxMetrics,
        host: str = "0.0.0.0",
        port: int = 8090,
    ) -> None:
        self.state = state
        self.metrics = metrics
        self.host = host
        self.port = port
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    def response_for(self, path: str) -> tuple[int, str, bytes]:
        if path == "/healthz":
            status = 200 if self.state.healthy else 503
            return status, "application/json", self._json(self.state.health_payload())
        if path == "/readyz":
            payload = self.state.readiness_payload()
            status = 200 if payload["status"] == "ready" else 503
            return status, "application/json", self._json(payload)
        if path == "/metrics":
            return 200, "text/plain; version=0.0.4", self.metrics.render_prometheus().encode("utf-8")
        return 404, "application/json", self._json({"error": "not_found"})

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=2)
            parts = line.decode("ascii", errors="replace").strip().split(" ")
            path = parts[1] if len(parts) >= 2 and parts[0] == "GET" else ""
            status, content_type, body = self.response_for(path)
            reason = "OK" if status == 200 else "Service Unavailable" if status == 503 else "Not Found"
            headers = (
                f"HTTP/1.1 {status} {reason}\r\n"
                f"Content-Type: {content_type}\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            writer.write(headers + body)
            await writer.drain()
        except (TimeoutError, ConnectionError, UnicodeError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    @staticmethod
    def _json(payload: Mapping[str, object]) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


DEFAULT_METRICS = SandboxMetrics()
