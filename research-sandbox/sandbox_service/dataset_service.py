"""Dataset lifecycle: validate first, persist metadata, then profile deterministically."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Protocol
from uuid import uuid4

from sandbox_service.domain.dataset_validation import DatasetValidator
from sandbox_service.domain.datasets import (
    DatasetClassification,
    DatasetProfile,
    DatasetRecord,
    DatasetStatus,
    DatasetUploadResult,
)
from sandbox_service.domain.errors import DatasetNotFound, DatasetValidationFailed
from sandbox_service.profiling import DeterministicDatasetProfiler


class DatasetRepository(Protocol):
    async def save_dataset(self, dataset: DatasetRecord) -> DatasetRecord: ...

    async def get_dataset(
        self, *, project_id: str, dataset_id: str, include_deleted: bool = False
    ) -> DatasetRecord | None: ...

    async def list_datasets(self, *, project_id: str) -> list[DatasetRecord]: ...

    async def save_dataset_profile(self, profile: DatasetProfile) -> DatasetProfile: ...

    async def list_dataset_profiles(self, *, project_id: str, dataset_id: str) -> list[DatasetProfile]: ...

    async def get_dataset_profile(
        self, *, project_id: str, dataset_id: str, version: int
    ) -> DatasetProfile | None: ...


class DatasetObjectStore(Protocol):
    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> str: ...

    async def get_bytes(self, *, key: str) -> bytes: ...

    async def delete(self, *, key: str) -> None: ...


class DatasetService:
    def __init__(
        self,
        *,
        repository: DatasetRepository,
        object_store: DatasetObjectStore,
        validator: DatasetValidator | None = None,
        profiler: DeterministicDatasetProfiler | None = None,
    ) -> None:
        self._repository = repository
        self._object_store = object_store
        self._validator = validator or DatasetValidator()
        self._profiler = profiler or DeterministicDatasetProfiler()

    async def upload(
        self,
        *,
        project_id: str,
        actor_id: str,
        filename: str,
        declared_media_type: str | None,
        classification: DatasetClassification,
        data: bytes,
    ) -> DatasetUploadResult:
        validated = self._validator.validate(
            filename=filename,
            data=data,
            declared_media_type=declared_media_type,
            classification=classification,
        )
        dataset_id = str(uuid4())
        storage_key = f"datasets/{project_id}/{dataset_id}/{PurePath(filename).name}"
        content_hash = hashlib.sha256(data).hexdigest()
        await self._object_store.put_bytes(
            key=storage_key, data=data, content_type=validated.media_type
        )
        record = DatasetRecord(
            dataset_id=dataset_id,
            project_id=project_id,
            owner_id=actor_id,
            filename=PurePath(filename).name,
            media_type=validated.media_type,
            size_bytes=len(data),
            content_hash=content_hash,
            storage_key=storage_key,
            classification=classification,
            status=DatasetStatus.VALIDATED,
        )
        try:
            await self._repository.save_dataset(record)
        except Exception:
            # Metadata is the authority for access.  If its durable write fails,
            # compensate the already-written object so an untracked upload is not
            # left behind indefinitely.  Preserve the original repository error.
            try:
                await self._object_store.delete(key=storage_key)
            except Exception:
                pass
            raise
        return DatasetUploadResult(**record.model_dump())

    async def list_datasets(self, *, project_id: str) -> list[DatasetUploadResult]:
        records = await self._repository.list_datasets(project_id=project_id)
        return [DatasetUploadResult(**record.model_dump()) for record in records]

    async def get_dataset(self, *, project_id: str, dataset_id: str) -> DatasetUploadResult:
        record = await self._require_dataset(project_id=project_id, dataset_id=dataset_id)
        return DatasetUploadResult(**record.model_dump())

    async def profile(self, *, project_id: str, dataset_id: str) -> DatasetProfile:
        record = await self._require_dataset(project_id=project_id, dataset_id=dataset_id)
        data = await self._object_store.get_bytes(key=record.storage_key)
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != record.content_hash:
            raise DatasetValidationFailed("Stored dataset content hash no longer matches metadata")
        existing = await self._repository.list_dataset_profiles(
            project_id=project_id, dataset_id=dataset_id
        )
        for profile in existing:
            if profile.content_hash == record.content_hash and profile.profiler_version == self._profiler.VERSION:
                return profile
        profile = self._profiler.profile(
            dataset_id=dataset_id,
            project_id=project_id,
            version=len(existing) + 1,
            content_hash=record.content_hash,
            media_type=record.media_type,
            data=data,
        )
        return await self._repository.save_dataset_profile(profile)

    async def get_profile(
        self, *, project_id: str, dataset_id: str, version: int
    ) -> DatasetProfile:
        await self._require_dataset(project_id=project_id, dataset_id=dataset_id)
        profile = await self._repository.get_dataset_profile(
            project_id=project_id, dataset_id=dataset_id, version=version
        )
        if profile is None:
            raise DatasetNotFound("Dataset profile was not found in this project")
        return profile

    async def list_profiles(
        self, *, project_id: str, dataset_id: str
    ) -> list[DatasetProfile]:
        """Return immutable profiles so clients can restore workflow state after reload."""

        await self._require_dataset(project_id=project_id, dataset_id=dataset_id)
        profiles = await self._repository.list_dataset_profiles(
            project_id=project_id, dataset_id=dataset_id
        )
        return sorted(profiles, key=lambda item: item.version)

    async def delete(self, *, project_id: str, dataset_id: str) -> None:
        record = await self._require_dataset(project_id=project_id, dataset_id=dataset_id)
        # Revoke access in authoritative metadata before deleting bytes.  A
        # transient object-store outage must never leave a deleted dataset
        # readable through the API; physical cleanup can be retried by retention
        # maintenance without undoing the tombstone.
        await self._repository.save_dataset(
            record.model_copy(
                update={"status": DatasetStatus.DELETED, "deleted_at": datetime.now(UTC)}
            )
        )
        try:
            await self._object_store.delete(key=record.storage_key)
        except Exception:
            # The soft-delete contract is fulfilled once metadata is tombstoned.
            # A production object store/retention worker retries physical cleanup.
            return

    async def _require_dataset(self, *, project_id: str, dataset_id: str) -> DatasetRecord:
        record = await self._repository.get_dataset(project_id=project_id, dataset_id=dataset_id)
        if record is None:
            # Deliberately indistinguishable between deletion, foreign project, and unknown ID.
            raise DatasetNotFound("Dataset was not found in this project")
        return record
