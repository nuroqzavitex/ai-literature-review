from io import BytesIO

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sandbox_service.api.datasets import router as dataset_router
from sandbox_service.api.dependencies import TrustedActorContext, get_actor_context
from sandbox_service.config import SandboxSettings
from sandbox_service.dataset_service import DatasetService
from sandbox_service.domain.dataset_validation import DatasetValidator
from sandbox_service.domain.datasets import DatasetClassification
from sandbox_service.domain.errors import (
    DatasetNotFound,
    DatasetTooLarge,
    DatasetTypeNotAllowed,
    DatasetValidationFailed,
)
from sandbox_service.repositories.memory import InMemorySandboxSessionRepository
from sandbox_service.storage import LocalObjectStore


class FailingSaveRepository(InMemorySandboxSessionRepository):
    async def save_dataset(self, dataset):
        raise RuntimeError("database unavailable")


class DeleteFailingStore(LocalObjectStore):
    async def delete(self, *, key: str) -> None:
        raise RuntimeError("object store unavailable")


def make_service(tmp_path) -> DatasetService:
    return DatasetService(
        repository=InMemorySandboxSessionRepository(),
        object_store=LocalObjectStore(tmp_path / "objects"),
    )


def xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["age", "group"])
    sheet.append([10, "A"])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def parquet_bytes() -> bytes:
    stream = BytesIO()
    pd.DataFrame({"age": [10, 20], "group": ["A", "B"]}).to_parquet(stream, engine="pyarrow", index=False)
    return stream.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content_type", "data"),
    [
        ("sample.csv", "text/csv", b"age,group\n10,A\n20,B\n"),
        (
            "sample.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            xlsx_bytes(),
        ),
        ("sample.parquet", "application/vnd.apache.parquet", parquet_bytes()),
    ],
)
async def test_upload_accepts_all_allowed_dataset_formats(tmp_path, filename, content_type, data) -> None:
    service = make_service(tmp_path)

    result = await service.upload(
        project_id="project-a",
        actor_id="user-a",
        filename=filename,
        declared_media_type=content_type,
        classification=DatasetClassification.NON_SENSITIVE,
        data=data,
    )

    assert result.status.value == "validated"
    assert result.project_id == "project-a"
    assert result.size_bytes == len(data)
    assert (await service.get_dataset(project_id="project-a", dataset_id=result.dataset_id)).content_hash == result.content_hash


def test_validator_rejects_oversized_mime_spoof_and_formula_injection() -> None:
    validator = DatasetValidator()
    validator.MAX_BYTES = 8
    with pytest.raises(DatasetTooLarge):
        validator.validate(
            filename="large.csv",
            data=b"value\n12345\n",
            declared_media_type="text/csv",
            classification=DatasetClassification.NON_SENSITIVE,
        )

    validator.MAX_BYTES = DatasetValidator.MAX_BYTES
    with pytest.raises(DatasetTypeNotAllowed):
        validator.validate(
            filename="spoof.csv",
            data=b"value\n1\n",
            declared_media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            classification=DatasetClassification.NON_SENSITIVE,
        )
    with pytest.raises(DatasetValidationFailed):
        validator.validate(
            filename="formula.csv",
            data=b"value\n=SUM(1,2)\n",
            declared_media_type="text/csv",
            classification=DatasetClassification.NON_SENSITIVE,
        )


@pytest.mark.asyncio
async def test_dataset_is_project_scoped_and_delete_revokes_access(tmp_path) -> None:
    service = make_service(tmp_path)
    uploaded = await service.upload(
        project_id="project-a",
        actor_id="user-a",
        filename="private.csv",
        declared_media_type="text/csv",
        classification=DatasetClassification.NON_SENSITIVE,
        data=b"value\n1\n",
    )

    with pytest.raises(DatasetNotFound):
        await service.get_dataset(project_id="project-b", dataset_id=uploaded.dataset_id)
    await service.delete(project_id="project-a", dataset_id=uploaded.dataset_id)
    with pytest.raises(DatasetNotFound):
        await service.get_dataset(project_id="project-a", dataset_id=uploaded.dataset_id)
    assert await service.list_datasets(project_id="project-a") == []


@pytest.mark.asyncio
async def test_upload_compensates_object_when_metadata_write_fails(tmp_path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    service = DatasetService(repository=FailingSaveRepository(), object_store=store)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.upload(
            project_id="project-a",
            actor_id="user-a",
            filename="orphan.csv",
            declared_media_type="text/csv",
            classification=DatasetClassification.NON_SENSITIVE,
            data=b"value\n1\n",
        )

    assert list((tmp_path / "objects").rglob("*.csv")) == []


@pytest.mark.asyncio
async def test_soft_delete_revokes_access_when_physical_cleanup_fails(tmp_path) -> None:
    repository = InMemorySandboxSessionRepository()
    store = DeleteFailingStore(tmp_path / "objects")
    service = DatasetService(repository=repository, object_store=store)
    uploaded = await service.upload(
        project_id="project-a",
        actor_id="user-a",
        filename="retained.csv",
        declared_media_type="text/csv",
        classification=DatasetClassification.NON_SENSITIVE,
        data=b"value\n1\n",
    )

    await service.delete(project_id="project-a", dataset_id=uploaded.dataset_id)

    with pytest.raises(DatasetNotFound):
        await service.get_dataset(project_id="project-a", dataset_id=uploaded.dataset_id)
    tombstone = repository.datasets[uploaded.dataset_id]
    assert tombstone.status.value == "deleted" and tombstone.deleted_at is not None


@pytest.mark.asyncio
async def test_local_object_store_uses_canonical_keys_and_atomic_writes(tmp_path) -> None:
    root = tmp_path / "objects"
    store = LocalObjectStore(root)

    assert await store.put_bytes(
        key="datasets/project-a/dataset-a/data.csv",
        data=b"value\n1\n",
        content_type="text/csv",
    ) == "datasets/project-a/dataset-a/data.csv"
    assert await store.get_bytes(key="datasets/project-a/dataset-a/data.csv") == b"value\n1\n"
    assert list(root.rglob(".sandbox-object-*")) == []

    for unsafe_key in ("../escape.csv", "..\\escape.csv", "/absolute.csv"):
        with pytest.raises(ValueError):
            await store.put_bytes(key=unsafe_key, data=b"x", content_type="text/plain")


def test_dataset_api_uploads_and_lists_project_scoped_metadata(tmp_path) -> None:
    service = make_service(tmp_path)
    app = FastAPI()
    app.state.dataset_service = service
    app.state.sandbox_settings = SandboxSettings(
        SANDBOX_ENABLED=True,
        SANDBOX_DATA_ANALYSIS_ENABLED=True,
    )
    app.dependency_overrides[get_actor_context] = lambda: TrustedActorContext(
        actor_id="user-a",
        project_id="project-a",
        correlation_id="dataset-api-test",
    )
    app.include_router(dataset_router)
    client = TestClient(app)

    created = client.post(
        "/api/v1/projects/project-a/datasets",
        files={"file": ("api.csv", b"value\n1\n", "text/csv")},
        headers={"X-Dataset-Classification": "non_sensitive", "X-Actor-Id": "user-a"},
    )
    listed = client.get("/api/v1/projects/project-a/datasets")

    assert created.status_code == 201
    assert created.json()["status"] == "validated"
    assert listed.status_code == 200
    assert [item["dataset_id"] for item in listed.json()] == [created.json()["dataset_id"]]

    dataset_id = created.json()["dataset_id"]
    profiled = client.post(f"/api/v1/projects/project-a/datasets/{dataset_id}/profile")
    profiles = client.get(f"/api/v1/projects/project-a/datasets/{dataset_id}/profiles")

    assert profiled.status_code == 201
    assert profiles.status_code == 200
    assert [item["profile_id"] for item in profiles.json()] == [profiled.json()["profile_id"]]
