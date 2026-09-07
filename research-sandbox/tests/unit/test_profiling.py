from io import BytesIO

from openpyxl import Workbook
import pandas as pd
import pytest

from sandbox_service.dataset_service import DatasetService
from sandbox_service.domain.datasets import DatasetClassification
from sandbox_service.profiling import DeterministicDatasetProfiler
from sandbox_service.repositories.memory import InMemorySandboxSessionRepository
from sandbox_service.storage import LocalObjectStore


def _xlsx_fixture() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["age", "group"])
    sheet.append([10, "A"])
    sheet.append([20, "B"])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _parquet_fixture() -> bytes:
    stream = BytesIO()
    pd.DataFrame({"age": [10, 20], "group": ["A", "B"]}).to_parquet(
        stream, engine="pyarrow", index=False
    )
    return stream.getvalue()


@pytest.mark.asyncio
async def test_profile_is_deterministic_versioned_and_reports_statistics(tmp_path) -> None:
    service = DatasetService(
        repository=InMemorySandboxSessionRepository(),
        object_store=LocalObjectStore(tmp_path / "objects"),
        profiler=DeterministicDatasetProfiler(),
    )
    uploaded = await service.upload(
        project_id="project-a",
        actor_id="user-a",
        filename="measurements.csv",
        declared_media_type="text/csv",
        classification=DatasetClassification.NON_SENSITIVE,
        data=b"age,group\n10,A\n20,B\n,A\n",
    )

    first = await service.profile(project_id="project-a", dataset_id=uploaded.dataset_id)
    second = await service.profile(project_id="project-a", dataset_id=uploaded.dataset_id)
    fetched = await service.get_profile(
        project_id="project-a", dataset_id=uploaded.dataset_id, version=1
    )

    age = next(column for column in first.columns if column.name == "age")
    group = next(column for column in first.columns if column.name == "group")
    assert first.version == 1
    assert first.profiler_version == "dataset_profiler.v1"
    assert first.content_hash == uploaded.content_hash
    assert first.row_count == 3 and first.column_count == 2
    assert age.missing_count == 1
    assert age.distribution == {
        "kind": "numeric",
        "count": 2,
        "min": 10,
        "max": 20,
        "mean": 15,
        "median": 15,
        "std": 7.0710678118654755,
    }
    assert group.distribution["top_values"] == [{"value": "A", "count": 2}, {"value": "B", "count": 1}]
    assert second == first == fetched


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "media_type", "payload"),
    [
        (
            "measurements.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            _xlsx_fixture(),
        ),
        ("measurements.parquet", "application/vnd.apache.parquet", _parquet_fixture()),
    ],
)
async def test_xlsx_and_parquet_profiles_match_the_same_deterministic_shape(
    tmp_path, filename, media_type, payload
) -> None:
    service = DatasetService(
        repository=InMemorySandboxSessionRepository(),
        object_store=LocalObjectStore(tmp_path / filename),
    )
    uploaded = await service.upload(
        project_id="project-a",
        actor_id="user-a",
        filename=filename,
        declared_media_type=media_type,
        classification=DatasetClassification.NON_SENSITIVE,
        data=payload,
    )

    profile = await service.profile(project_id="project-a", dataset_id=uploaded.dataset_id)

    assert profile.row_count == 2 and profile.column_count == 2
    assert [column.name for column in profile.columns] == ["age", "group"]
    age = profile.columns[0]
    assert age.distribution["mean"] == 15
    assert profile.profile_hash == (
        await service.profile(project_id="project-a", dataset_id=uploaded.dataset_id)
    ).profile_hash
