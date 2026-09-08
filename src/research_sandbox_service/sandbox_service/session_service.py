"""S0 lifecycle service: explicit session creation only, never autonomous work."""

from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from sandbox_service.domain.errors import (
    SandboxSessionNotFound,
    SandboxSessionStateError,
    SourceNotReviewed,
)
from sandbox_service.domain.ports import ResearchContextProvider
from sandbox_service.domain.sessions import (
    CreateSandboxSessionRequest,
    ResearchContextSnapshot,
    SandboxEntrypoint,
    SandboxSessionResponse,
    SandboxSessionStatus,
    SandboxSessionStatusHistory,
)


class SandboxSessionRepository(Protocol):
    async def save_context_snapshot(self, snapshot: ResearchContextSnapshot) -> None: ...

    async def get_context_snapshot(
        self, *, context_id: str
    ) -> ResearchContextSnapshot | None: ...

    async def create_session(self, session: SandboxSessionResponse) -> SandboxSessionResponse: ...

    async def get_session(
        self, *, project_id: str, session_id: str
    ) -> SandboxSessionResponse | None: ...

    async def list_sessions(self, *, project_id: str) -> list[SandboxSessionResponse]: ...

    async def update_session_status(
        self,
        session: SandboxSessionResponse,
        *,
        changed_by: str,
        reason: str | None = None,
    ) -> SandboxSessionResponse: ...

    async def list_session_status_history(
        self, *, project_id: str, session_id: str
    ) -> list[SandboxSessionStatusHistory]: ...


class SandboxSessionService:
    """Coordinates authorization-bound context pinning with sandbox-owned storage.

    This service intentionally has no ProjectAIClient or SandboxExecutor dependency:
    creating a session is a synchronous, on-demand persistence operation only.
    """

    def __init__(
        self,
        *,
        repository: SandboxSessionRepository,
        context_provider: ResearchContextProvider | None = None,
    ) -> None:
        self._repository = repository
        self._context_provider = context_provider

    async def create_session(
        self,
        *,
        project_id: str,
        request: CreateSandboxSessionRequest,
        actor_id: str,
        correlation_id: str | None = None,
    ) -> SandboxSessionResponse:
        correlation_id = correlation_id or str(uuid4())
        snapshot: ResearchContextSnapshot | None = None

        if request.entrypoint is not SandboxEntrypoint.MANUAL:
            if self._context_provider is None:
                raise SourceNotReviewed("A trusted research context provider is required")
            snapshot = await self._context_provider.resolve_snapshot(
                project_id=project_id,
                entrypoint=request.entrypoint,
                source_resource_id=request.source_resource_id or "",
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
            if snapshot.project_id != project_id:
                raise SourceNotReviewed(
                    "The resolved research context is outside the requested project"
                )
            if snapshot.source_type is not request.entrypoint:
                raise SourceNotReviewed("The trusted context does not match the entrypoint")
            await self._repository.save_context_snapshot(snapshot)

        now = datetime.now(timezone.utc)
        session = SandboxSessionResponse(
            session_id=str(uuid4()),
            project_id=project_id,
            mode=request.mode,
            entrypoint=request.entrypoint,
            source_resource_id=request.source_resource_id,
            title=request.title,
            initial_question=request.initial_question,
            status=SandboxSessionStatus.DRAFT,
            creator_id=actor_id,
            context_snapshot_id=snapshot.context_id if snapshot else None,
            context_hash=snapshot.content_hash if snapshot else None,
            created_at=now,
            updated_at=now,
        )
        return await self._repository.create_session(session)

    async def get_session(
        self, *, project_id: str, session_id: str
    ) -> SandboxSessionResponse:
        session = await self._repository.get_session(
            project_id=project_id, session_id=session_id
        )
        if session is None:
            # Return not-found for an out-of-project ID to avoid revealing its existence.
            raise SandboxSessionNotFound("Sandbox session was not found in this project")
        return session

    async def list_sessions(self, *, project_id: str) -> list[SandboxSessionResponse]:
        return await self._repository.list_sessions(project_id=project_id)

    async def get_session_context(
        self, *, project_id: str, session_id: str
    ) -> ResearchContextSnapshot | None:
        session = await self.get_session(project_id=project_id, session_id=session_id)
        if not session.context_snapshot_id:
            return None
        snapshot = await self._repository.get_context_snapshot(
            context_id=session.context_snapshot_id
        )
        if snapshot is None or snapshot.project_id != project_id:
            raise SandboxSessionNotFound(
                "The pinned research context was not found in this project"
            )
        return snapshot

    async def close_session(
        self, *, project_id: str, session_id: str, actor_id: str
    ) -> SandboxSessionResponse:
        session = await self.get_session(project_id=project_id, session_id=session_id)
        if session.status is SandboxSessionStatus.COMPLETED:
            return session
        if session.status is SandboxSessionStatus.DISCARDED:
            raise SandboxSessionStateError("A discarded session cannot be completed")
        return await self._repository.update_session_status(
            session.model_copy(
                update={
                    "status": SandboxSessionStatus.COMPLETED,
                    "updated_at": datetime.now(timezone.utc),
                }
            ),
            changed_by=actor_id,
            reason="closed_by_user",
        )

    async def discard_session(
        self, *, project_id: str, session_id: str, actor_id: str
    ) -> SandboxSessionResponse:
        session = await self.get_session(project_id=project_id, session_id=session_id)
        if session.status is SandboxSessionStatus.DISCARDED:
            return session
        if session.status is SandboxSessionStatus.COMPLETED:
            raise SandboxSessionStateError("A completed session cannot be discarded")
        return await self._repository.update_session_status(
            session.model_copy(
                update={
                    "status": SandboxSessionStatus.DISCARDED,
                    "updated_at": datetime.now(timezone.utc),
                }
            ),
            changed_by=actor_id,
            reason="discarded_by_user",
        )

    async def list_status_history(
        self, *, project_id: str, session_id: str
    ) -> list[SandboxSessionStatusHistory]:
        await self.get_session(project_id=project_id, session_id=session_id)
        return await self._repository.list_session_status_history(
            project_id=project_id, session_id=session_id
        )
