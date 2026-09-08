"""Canonical HMAC service authentication and signed context snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
from threading import Lock
from typing import Any, Mapping, Protocol

from sandbox_service.domain.sessions import ResearchContextSnapshot


class ServiceAuthError(ValueError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class ReplayStore(Protocol):
    """Atomic nonce consumption; production may back this with Postgres/Redis."""

    def consume(self, *, key_id: str, nonce: str, expires_at: int, now: int) -> bool: ...


class InMemoryReplayStore:
    """Bounded local replay cache for single-process development and tests."""

    def __init__(self, *, max_entries: int = 10_000) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._entries: dict[tuple[str, str], int] = {}
        self._lock = Lock()

    def consume(self, *, key_id: str, nonce: str, expires_at: int, now: int) -> bool:
        key = (key_id, nonce)
        with self._lock:
            expired = [item for item, expiry in self._entries.items() if expiry <= now]
            for item in expired:
                self._entries.pop(item, None)
            if key in self._entries:
                return False
            if len(self._entries) >= self._max_entries:
                oldest = min(self._entries, key=self._entries.__getitem__)
                self._entries.pop(oldest, None)
            self._entries[key] = expires_at
            return True


class SignedServiceAuth:
    """HMAC request authentication with body binding, expiry, and nonce replay checks."""

    def __init__(
        self,
        *,
        signing_key: bytes,
        key_id: str = "sandbox-v1",
        max_age_seconds: int = 300,
        verification_keys: Mapping[str, bytes] | None = None,
        replay_store: ReplayStore | None = None,
    ) -> None:
        if len(signing_key) < 32:
            raise ValueError("service signing key must contain at least 32 bytes")
        self._key = signing_key
        self.key_id = key_id
        self.max_age_seconds = max_age_seconds
        self._keys = dict(verification_keys or {})
        self._keys[key_id] = signing_key
        if any(len(value) < 32 for value in self._keys.values()):
            raise ValueError("every service verification key must contain at least 32 bytes")
        self._replay_store = replay_store or InMemoryReplayStore()

    def sign(
        self,
        *,
        method: str,
        path: str,
        body: Mapping[str, Any],
        project_id: str,
        actor_id: str,
        correlation_id: str,
        now: datetime | None = None,
        nonce: str | None = None,
    ) -> dict[str, str]:
        return self.sign_bytes(
            method=method,
            path=path,
            body=canonical_json(body),
            project_id=project_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            now=now,
            nonce=nonce,
        )

    def sign_bytes(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        project_id: str,
        actor_id: str,
        correlation_id: str,
        now: datetime | None = None,
        nonce: str | None = None,
    ) -> dict[str, str]:
        timestamp = str(int((now or datetime.now(timezone.utc)).timestamp()))
        nonce = nonce or secrets.token_urlsafe(24)
        digest = hashlib.sha256(body).hexdigest()
        signature = self._signature(method, path, digest, project_id, actor_id, correlation_id, timestamp, nonce)
        return {
            "X-Sandbox-Key-Id": self.key_id,
            "X-Sandbox-Timestamp": timestamp,
            "X-Sandbox-Nonce": nonce,
            "X-Sandbox-Project-Id": project_id,
            "X-Sandbox-Actor-Id": actor_id,
            "X-Correlation-Id": correlation_id,
            "X-Sandbox-Content-SHA256": digest,
            "X-Sandbox-Signature": signature,
        }

    def verify(
        self,
        *,
        method: str,
        path: str,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
        now: datetime | None = None,
    ) -> tuple[str, str, str]:
        return self.verify_bytes(
            method=method,
            path=path,
            body=canonical_json(body),
            headers=headers,
            now=now,
        )

    def verify_bytes(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        headers: Mapping[str, str],
        now: datetime | None = None,
    ) -> tuple[str, str, str]:
        """Verify the exact HTTP entity bytes used by the core BFF.

        This is required for multipart uploads: parsing and re-serializing the
        body before verification would break body binding and permit ambiguous
        representations at the trust boundary.
        """

        normalized = {key.lower(): value for key, value in headers.items()}
        try:
            key_id = normalized["x-sandbox-key-id"]
            timestamp = normalized["x-sandbox-timestamp"]
            nonce = normalized["x-sandbox-nonce"]
            project_id = normalized["x-sandbox-project-id"]
            actor_id = normalized["x-sandbox-actor-id"]
            correlation_id = normalized["x-correlation-id"]
            received_digest = normalized["x-sandbox-content-sha256"]
            received = normalized["x-sandbox-signature"]
        except KeyError as exc:
            raise ServiceAuthError("missing signed service-auth header") from exc
        verification_key = self._keys.get(key_id)
        if verification_key is None:
            raise ServiceAuthError("unknown service-auth key id")
        try:
            current_timestamp = int((now or datetime.now(timezone.utc)).timestamp())
            signed_timestamp = int(timestamp)
            age = abs(current_timestamp - signed_timestamp)
        except ValueError as exc:
            raise ServiceAuthError("invalid service-auth timestamp") from exc
        if age > self.max_age_seconds:
            raise ServiceAuthError("expired service-auth request")
        digest = hashlib.sha256(body).hexdigest()
        if not hmac.compare_digest(received_digest, digest):
            raise ServiceAuthError("service-auth content digest mismatch")
        expected = self._signature(
            method, path, digest, project_id, actor_id, correlation_id, timestamp, nonce,
            key=verification_key,
        )
        if not hmac.compare_digest(received, expected):
            raise ServiceAuthError("invalid service-auth signature")
        if not self._replay_store.consume(
            key_id=key_id,
            nonce=nonce,
            expires_at=signed_timestamp + self.max_age_seconds + 1,
            now=current_timestamp,
        ):
            raise ServiceAuthError("replayed service-auth request")
        return project_id, actor_id, correlation_id

    def _signature(self, method: str, path: str, digest: str, project_id: str, actor_id: str, correlation_id: str, timestamp: str, nonce: str, *, key: bytes | None = None) -> str:
        canonical = "\n".join((method.upper(), path, digest, project_id, actor_id, correlation_id, timestamp, nonce))
        return hmac.new(key or self._key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


class ContextSnapshotSigner:
    """Signs the immutable snapshot after its deterministic content hash is computed."""

    def __init__(
        self,
        *,
        signing_key: bytes,
        key_id: str = "sandbox-context-v1",
        verification_keys: Mapping[str, bytes] | None = None,
    ) -> None:
        if len(signing_key) < 32:
            raise ValueError("context signing key must contain at least 32 bytes")
        self._key = signing_key
        self.key_id = key_id
        self._keys = dict(verification_keys or {})
        self._keys[key_id] = signing_key
        if any(len(value) < 32 for value in self._keys.values()):
            raise ValueError("every context verification key must contain at least 32 bytes")

    def sign(self, snapshot: ResearchContextSnapshot) -> ResearchContextSnapshot:
        unsigned = snapshot.model_copy(update={"signing_key_id": self.key_id, "signature": None})
        signature = hmac.new(self._key, canonical_json(unsigned.model_dump(mode="json", exclude={"signature"})), hashlib.sha256).hexdigest()
        return unsigned.model_copy(update={"signature": signature})

    def verify(self, snapshot: ResearchContextSnapshot) -> None:
        verification_key = self._keys.get(snapshot.signing_key_id or "")
        if verification_key is None or not snapshot.signature:
            raise ServiceAuthError("missing or unknown context signature")
        unsigned = snapshot.model_copy(update={"signature": None})
        expected = hmac.new(
            verification_key,
            canonical_json(unsigned.model_dump(mode="json", exclude={"signature"})),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(snapshot.signature, expected or ""):
            raise ServiceAuthError("invalid context signature")
