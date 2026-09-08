"""Canonical HMAC signing and verification for sealed execution manifests."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json

from sandbox_service.domain.execution import SandboxExecutionManifest


class ManifestVerificationError(ValueError):
    pass


class ManifestSigner:
    def __init__(self, *, signing_key: bytes, key_id: str = "sandbox-hmac-v1") -> None:
        if len(signing_key) < 32:
            raise ValueError("Manifest signing key must be at least 32 bytes")
        self._key = signing_key
        self.key_id = key_id

    def sign(self, manifest: SandboxExecutionManifest) -> SandboxExecutionManifest:
        payload = self._canonical_payload(manifest)
        signature = hmac.new(self._key, payload, hashlib.sha256).hexdigest()
        return manifest.model_copy(update={"signature": signature})

    def verify(self, manifest: SandboxExecutionManifest, *, now: datetime | None = None) -> None:
        if not manifest.signature:
            raise ManifestVerificationError("Manifest is unsigned")
        expected = hmac.new(self._key, self._canonical_payload(manifest), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, manifest.signature):
            raise ManifestVerificationError("Manifest signature mismatch")
        current = now or datetime.now(timezone.utc)
        if manifest.issued_at > current or manifest.expires_at <= current:
            raise ManifestVerificationError("Manifest is expired or not yet valid")

    @staticmethod
    def _canonical_payload(manifest: SandboxExecutionManifest) -> bytes:
        body = manifest.model_dump(mode="json", exclude={"signature"})
        return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
