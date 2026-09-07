"""Direct, project-scoped dataset upload and deterministic profile endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, Request, Response, UploadFile, status

from sandbox_service.api.dependencies import (
    get_actor_context,
    get_actor_id,
    require_data_analysis_enabled,
)
from sandbox_service.api.openapi import SANDBOX_ERROR_RESPONSES
from sandbox_service.api.sessions import _http_error
from sandbox_service.dataset_service import DatasetService
from sandbox_service.domain.datasets import (
    DatasetClassification,
    DatasetProfile,
    DatasetUploadResult,
)
from sandbox_service.domain.errors import SandboxDomainError

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/datasets",
    tags=["sandbox-datasets"],
    dependencies=[Depends(require_data_analysis_enabled), Depends(get_actor_context)],
    responses=SANDBOX_ERROR_RESPONSES,
)


def get_dataset_service(request: Request) -> DatasetService:
    return request.app.state.dataset_service


@router.post("", response_model=DatasetUploadResult, status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    project_id: str,
    file: Annotated[UploadFile, File(...)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
    actor_id: Annotated[str, Depends(get_actor_id)],
    classification: Annotated[DatasetClassification, Header(alias="X-Dataset-Classification")] = DatasetClassification.NON_SENSITIVE,
) -> DatasetUploadResult:
    try:
        return await service.upload(
            project_id=project_id,
            actor_id=actor_id,
            filename=file.filename or "",
            declared_media_type=file.content_type,
            classification=classification,
            data=await file.read(),
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error
    finally:
        await file.close()


@router.get("", response_model=list[DatasetUploadResult])
async def list_datasets(
    project_id: str,
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> list[DatasetUploadResult]:
    return await service.list_datasets(project_id=project_id)


@router.get("/{dataset_id}", response_model=DatasetUploadResult)
async def get_dataset(
    project_id: str,
    dataset_id: str,
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> DatasetUploadResult:
    try:
        return await service.get_dataset(project_id=project_id, dataset_id=dataset_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post("/{dataset_id}/profile", response_model=DatasetProfile, status_code=status.HTTP_201_CREATED)
async def profile_dataset(
    project_id: str,
    dataset_id: str,
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> DatasetProfile:
    try:
        return await service.profile(project_id=project_id, dataset_id=dataset_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get("/{dataset_id}/profiles/{version}", response_model=DatasetProfile)
async def get_dataset_profile(
    project_id: str,
    dataset_id: str,
    version: int,
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> DatasetProfile:
    try:
        return await service.get_profile(project_id=project_id, dataset_id=dataset_id, version=version)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get("/{dataset_id}/profiles", response_model=list[DatasetProfile])
async def list_dataset_profiles(
    project_id: str,
    dataset_id: str,
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> list[DatasetProfile]:
    try:
        return await service.list_profiles(project_id=project_id, dataset_id=dataset_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(
    project_id: str,
    dataset_id: str,
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> Response:
    try:
        await service.delete(project_id=project_id, dataset_id=dataset_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except SandboxDomainError as error:
        raise _http_error(error) from error
