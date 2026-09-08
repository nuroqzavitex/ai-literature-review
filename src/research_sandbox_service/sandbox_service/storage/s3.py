"""S3-compatible shared object storage adapter for production deployments."""

from __future__ import annotations

import asyncio
from pathlib import PurePosixPath
from typing import Any

import boto3
from botocore.config import Config


class S3ObjectStore:
    """Small async facade over boto3 with server-owned, canonical object keys."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region_name: str = "us-east-1",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        server_side_encryption: str | None = None,
    ) -> None:
        if not bucket.strip():
            raise ValueError("Object storage bucket cannot be blank")
        self._bucket = bucket
        self._server_side_encryption = server_side_encryption
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> str:
        canonical = self._key(key)
        options: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": canonical,
            "Body": data,
            "ContentType": content_type,
        }
        if self._server_side_encryption:
            options["ServerSideEncryption"] = self._server_side_encryption
        await asyncio.to_thread(self._client.put_object, **options)
        return canonical

    async def get_bytes(self, *, key: str) -> bytes:
        canonical = self._key(key)
        return await asyncio.to_thread(self._get_sync, canonical)

    async def delete(self, *, key: str) -> None:
        canonical = self._key(key)
        await asyncio.to_thread(
            self._client.delete_object, Bucket=self._bucket, Key=canonical
        )

    async def healthcheck(self) -> None:
        """Fail readiness when the configured bucket is unavailable."""
        await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)

    async def ready(self) -> bool:
        try:
            await self.healthcheck()
        except Exception:
            return False
        return True

    def _get_sync(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        stream = response["Body"]
        try:
            return stream.read()
        finally:
            stream.close()

    @staticmethod
    def _key(key: str) -> str:
        path = PurePosixPath(key)
        if (
            not key
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in key
            or any(part in {"", "."} for part in path.parts)
        ):
            raise ValueError("Object storage key must be relative and canonical")
        return path.as_posix()
