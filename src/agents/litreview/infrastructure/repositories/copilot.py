from __future__ import annotations

import hashlib
import json
import secrets
import threading
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, case, delete, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config import get_settings
from src.db.models import (
    V2ActionProposal,
    V2Actor,
    V2AuditEvent,
    V2Conversation,
    V2Event,
    V2Gap,
    V2GapDecision,
    V2Memory,
    V2Message,
    V2MessageCitation,
    V2Project,
    V2ProjectInvitation,
    V2ProjectMembership,
    V2ProjectReviewJob,
    V2ReportVersion,
    V2ResearchPlan,
    V2ReviewAssignment,
    V2ReviewerFeedback,
    V2ReviewSubmission,
    V2Session,
)
from src.db.session import session_scope
from src.services.repositories.database import is_postgres_url, run_migrations


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _loads(value: str | None, default: Any) -> Any:
    return json.loads(value) if value else default


def _invitation_row(row: Any) -> dict[str, Any]:
    value = dict(row)
    value.pop("token_hash", None)
    return value


class ProjectResearchBusyError(RuntimeError):
    """Raised when another thread is already using the project's agent."""


class V2Repository:
    """MVP2 persistence with immutable versions and project-scoped records."""

    def __init__(self, database_url: str | None = None, *, initialize: bool = True) -> None:
        settings = get_settings()
        self.database_url = database_url or settings.product_database_url or settings.database_url
        self.is_postgres = is_postgres_url(self.database_url)
        self.path = None
        self._lock = threading.RLock()
        if initialize:
            self.initialize()

    def _connect(self) -> Any:
        return session_scope(self.database_url)

    def _write_lock(self) -> Any:
        """PostgreSQL handles concurrent writers; no process-local write lock."""
        return nullcontext() if self.is_postgres else self._lock

    def initialize(self) -> None:
        with self._lock:
            run_migrations(self.database_url)

    # Authentication and projects
    def upsert_actor(
        self,
        actor_id: str,
        display_name: str | None = None,
        email: str | None = None,
        image_url: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        actor_insert = pg_insert(V2Actor)
        stmt = (
            actor_insert.values(
                actor_id=actor_id,
                display_name=display_name or actor_id,
                actor_type="researcher",
                email=email,
                image_url=image_url,
                deleted_at=None,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[V2Actor.actor_id],
                set_={
                    "display_name": func.coalesce(
                        func.nullif(actor_insert.excluded.display_name, ""), V2Actor.display_name
                    ),
                    "email": func.coalesce(actor_insert.excluded.email, V2Actor.email),
                    "image_url": func.coalesce(actor_insert.excluded.image_url, V2Actor.image_url),
                    "deleted_at": None,
                    "updated_at": actor_insert.excluded.updated_at,
                },
            )
            .returning(*V2Actor.__table__.c)
        )
        with self._write_lock(), self._connect() as connection:
            row = connection.execute(stmt).mappings().one_or_none()
        return dict(row) if row else {}

    def soft_delete_actor(self, actor_id: str) -> None:
        with self._write_lock(), self._connect() as connection:
            now = utc_now()
            connection.execute(
                update(V2Actor)
                .where(V2Actor.actor_id == actor_id)
                .values(deleted_at=now, email=None, image_url=None, updated_at=now)
            )

    def create_session(self, bootstrap_token: str) -> tuple[str, dict[str, Any], str]:
        # Pilot bootstrap tokens are "researcher:<id>" or "reviewer:<id>". The
        # returned session is random and only its hash is persisted.
        role, separator, actor_id = bootstrap_token.partition(":")
        if not separator or role not in {"researcher", "reviewer", "admin"} or not actor_id.strip():
            raise ValueError("Invalid pilot bootstrap token")
        actor_id = actor_id.strip()[:100]
        now = utc_now()
        expires_at = (datetime.now(UTC) + timedelta(hours=12)).isoformat()
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                pg_insert(V2Actor)
                .values(
                    actor_id=actor_id,
                    display_name=actor_id,
                    actor_type=role,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[V2Actor.actor_id],
                    set_={"actor_type": role, "updated_at": now},
                )
            )
            connection.execute(
                pg_insert(V2Session).values(
                    session_hash=token_hash,
                    actor_id=actor_id,
                    expires_at=expires_at,
                    created_at=now,
                )
            )
        return raw_token, {"actor_id": actor_id, "display_name": actor_id, "actor_type": role}, expires_at

    def resolve_session(self, raw_token: str | None) -> dict[str, Any] | None:
        if not raw_token:
            return None
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        with self._connect() as connection:
            row = (
                connection.execute(
                    select(V2Actor.__table__)
                    .select_from(V2Session.__table__.join(V2Actor.__table__, V2Actor.actor_id == V2Session.actor_id))
                    .where(
                        V2Session.session_hash == token_hash,
                        V2Session.revoked_at.is_(None),
                        V2Session.expires_at > utc_now(),
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    def revoke_session(self, raw_token: str) -> None:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                update(V2Session).where(V2Session.session_hash == token_hash).values(revoked_at=utc_now())
            )

    def create_project(self, actor_id: str, name: str, description: str) -> dict[str, Any]:
        project_id, now = new_id("prj"), utc_now()
        with self._write_lock(), self._connect() as connection:
            project = (
                connection.execute(
                    pg_insert(V2Project)
                    .values(
                        project_id=project_id,
                        name=name,
                        description=description,
                        owner_id=actor_id,
                        active_report_version_id=None,
                        created_at=now,
                        updated_at=now,
                    )
                    .returning(*V2Project.__table__.c)
                )
                .mappings()
                .one()
            )
            connection.execute(
                pg_insert(V2ProjectMembership).values(
                    project_id=project_id,
                    actor_id=actor_id,
                    project_role="owner",
                    created_at=now,
                )
            )
        return dict(project)

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = (
                connection.execute(select(V2Project.__table__).where(V2Project.project_id == project_id))
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    def list_memberships(self, actor_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = (
                connection.execute(
                    select(V2ProjectMembership.__table__, V2Project.name)
                    .select_from(
                        V2ProjectMembership.__table__.join(
                            V2Project.__table__, V2Project.project_id == V2ProjectMembership.project_id
                        )
                    )
                    .where(V2ProjectMembership.actor_id == actor_id)
                    .order_by(V2ProjectMembership.created_at)
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def list_projects(self, actor_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = (
                connection.execute(
                    select(V2Project.__table__, V2ProjectMembership.project_role)
                    .select_from(
                        V2ProjectMembership.__table__.join(
                            V2Project.__table__, V2Project.project_id == V2ProjectMembership.project_id
                        )
                    )
                    .where(V2ProjectMembership.actor_id == actor_id)
                    .order_by(V2Project.updated_at.desc())
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def membership(self, project_id: str, actor_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = (
                connection.execute(
                    select(V2ProjectMembership.__table__).where(
                        V2ProjectMembership.project_id == project_id,
                        V2ProjectMembership.actor_id == actor_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    def add_member(self, project_id: str, actor_id: str, role: str) -> dict[str, Any]:
        now = utc_now()
        actor_type = "reviewer" if role == "reviewer" else "researcher"
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                pg_insert(V2Actor)
                .values(
                    actor_id=actor_id,
                    display_name=actor_id,
                    actor_type=actor_type,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=[V2Actor.actor_id])
            )
            connection.execute(
                pg_insert(V2ProjectMembership)
                .values(project_id=project_id, actor_id=actor_id, project_role=role, created_at=now)
                .on_conflict_do_update(
                    index_elements=[V2ProjectMembership.project_id, V2ProjectMembership.actor_id],
                    set_={"project_role": role, "created_at": now},
                )
            )
        return self.membership(project_id, actor_id) or {}

    def list_project_members(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = (
                connection.execute(
                    select(V2ProjectMembership.__table__, V2Actor.display_name, V2Actor.actor_type)
                    .select_from(
                        V2ProjectMembership.__table__.join(
                            V2Actor.__table__, V2Actor.actor_id == V2ProjectMembership.actor_id
                        )
                    )
                    .where(V2ProjectMembership.project_id == project_id)
                    .order_by(V2ProjectMembership.created_at)
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    # Review library, invitations and assignments
    def list_review_links(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            latest_report_version_id = (
                select(V2ReportVersion.report_version_id)
                .where(
                    V2ReportVersion.project_id == V2ProjectReviewJob.project_id,
                    V2ReportVersion.job_id == V2ProjectReviewJob.job_id,
                )
                .order_by(V2ReportVersion.version_number.desc())
                .limit(1)
                .correlate(V2ProjectReviewJob.__table__)
                .scalar_subquery()
            )
            rows = (
                connection.execute(
                    select(
                        V2ProjectReviewJob.__table__,
                        V2Actor.display_name.label("requested_by_name"),
                        V2ReportVersion.report_version_id,
                        V2ReportVersion.version_number,
                        V2ReportVersion.created_at.label("report_created_at"),
                    )
                    .select_from(
                        V2ProjectReviewJob.__table__.join(
                            V2Actor.__table__, V2Actor.actor_id == V2ProjectReviewJob.requested_by
                        ).outerjoin(
                            V2ReportVersion.__table__, V2ReportVersion.report_version_id == latest_report_version_id
                        )
                    )
                    .where(V2ProjectReviewJob.project_id == project_id)
                    .order_by(V2ProjectReviewJob.created_at.desc())
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def create_invitation(
        self, project_id: str, job_id: str, email: str, invited_by: str, ttl_days: int = 7
    ) -> tuple[dict[str, Any], str]:
        invitation_id, raw_token, now = new_id("inv"), secrets.token_urlsafe(32), utc_now()
        expires_at = (datetime.now(UTC) + timedelta(days=ttl_days)).isoformat()
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        normalized_email = email.strip().lower()
        with self._write_lock(), self._connect() as connection:
            row = (
                connection.execute(
                    pg_insert(V2ProjectInvitation)
                    .values(
                        invitation_id=invitation_id,
                        project_id=project_id,
                        job_id=job_id,
                        email=normalized_email,
                        token_hash=token_hash,
                        status="pending",
                        invited_by=invited_by,
                        expires_at=expires_at,
                        created_at=now,
                    )
                    .on_conflict_do_update(
                        index_elements=[
                            V2ProjectInvitation.project_id,
                            V2ProjectInvitation.job_id,
                            V2ProjectInvitation.email,
                        ],
                        set_={
                            "token_hash": token_hash,
                            "status": "pending",
                            "invited_by": invited_by,
                            "expires_at": expires_at,
                            "created_at": now,
                            "accepted_by": None,
                            "responded_at": None,
                            "email_delivery_status": "not_configured",
                            "email_attempts": 0,
                            "last_email_attempt_at": None,
                            "email_sent_at": None,
                            "email_error": None,
                            "resend_email_id": None,
                        },
                    )
                    .returning(*V2ProjectInvitation.__table__.c)
                )
                .mappings()
                .one()
            )
        return _invitation_row(row), raw_token

    def invitation_context(self, project_id: str, invitation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = (
                connection.execute(
                    select(
                        V2ProjectInvitation.__table__,
                        V2Project.name.label("project_name"),
                        V2ProjectReviewJob.topic,
                        V2Actor.display_name.label("inviter_name"),
                    )
                    .select_from(
                        V2ProjectInvitation.__table__.join(
                            V2Project.__table__, V2Project.project_id == V2ProjectInvitation.project_id
                        )
                        .join(
                            V2ProjectReviewJob.__table__,
                            and_(
                                V2ProjectReviewJob.project_id == V2ProjectInvitation.project_id,
                                V2ProjectReviewJob.job_id == V2ProjectInvitation.job_id,
                            ),
                        )
                        .join(V2Actor.__table__, V2Actor.actor_id == V2ProjectInvitation.invited_by)
                    )
                    .where(
                        V2ProjectInvitation.project_id == project_id,
                        V2ProjectInvitation.invitation_id == invitation_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _invitation_row(row) if row else None

    def mark_invitation_email_delivery(
        self,
        project_id: str,
        invitation_id: str,
        delivery_status: str,
        *,
        resend_email_id: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        attempted = delivery_status in {"sent", "failed"}
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                update(V2ProjectInvitation)
                .where(
                    V2ProjectInvitation.project_id == project_id,
                    V2ProjectInvitation.invitation_id == invitation_id,
                )
                .values(
                    email_delivery_status=delivery_status,
                    email_attempts=V2ProjectInvitation.email_attempts + (1 if attempted else 0),
                    last_email_attempt_at=now if attempted else V2ProjectInvitation.last_email_attempt_at,
                    email_sent_at=now if delivery_status == "sent" else V2ProjectInvitation.email_sent_at,
                    email_error=error[:1000] if error else None,
                    resend_email_id=func.coalesce(literal(resend_email_id), V2ProjectInvitation.resend_email_id),
                )
            )
        return self.invitation_context(project_id, invitation_id)

    def rotate_invitation_token(
        self, project_id: str, invitation_id: str, min_interval_seconds: int
    ) -> tuple[dict[str, Any], str]:
        invitation = self.invitation_context(project_id, invitation_id)
        if not invitation or invitation["status"] != "pending" or invitation["expires_at"] <= utc_now():
            raise ValueError("Invitation is invalid, expired, or already used")
        last_attempt = invitation.get("last_email_attempt_at")
        if last_attempt:
            elapsed = datetime.now(UTC) - datetime.fromisoformat(last_attempt)
            if elapsed.total_seconds() < min_interval_seconds:
                remaining = max(1, min_interval_seconds - int(elapsed.total_seconds()))
                raise RuntimeError(f"Please wait {remaining} seconds before sending again")
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                update(V2ProjectInvitation)
                .where(
                    V2ProjectInvitation.project_id == project_id,
                    V2ProjectInvitation.invitation_id == invitation_id,
                )
                .values(
                    token_hash=token_hash,
                    email_delivery_status="not_configured",
                    email_error=None,
                    resend_email_id=None,
                )
            )
        refreshed = self.invitation_context(project_id, invitation_id)
        if not refreshed:
            raise ValueError("Invitation not found")
        return refreshed, raw_token

    def get_invitation(self, raw_token: str) -> dict[str, Any] | None:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        with self._connect() as connection:
            row = (
                connection.execute(
                    select(V2ProjectInvitation.__table__, V2Project.name.label("project_name"))
                    .select_from(
                        V2ProjectInvitation.__table__.join(
                            V2Project.__table__, V2Project.project_id == V2ProjectInvitation.project_id
                        )
                    )
                    .where(V2ProjectInvitation.token_hash == token_hash)
                )
                .mappings()
                .one_or_none()
            )
        invitation = _invitation_row(row) if row else None
        if invitation and invitation["status"] == "pending" and invitation["expires_at"] < utc_now():
            with self._write_lock(), self._connect() as connection:
                connection.execute(
                    update(V2ProjectInvitation)
                    .where(V2ProjectInvitation.invitation_id == invitation["invitation_id"])
                    .values(status="expired", responded_at=utc_now())
                )
            invitation["status"] = "expired"
        return invitation

    def accept_invitation(self, raw_token: str, actor_id: str) -> dict[str, Any]:
        invitation = self.get_invitation(raw_token)
        if not invitation or invitation["status"] != "pending":
            raise ValueError("Invitation is invalid, expired, or already used")
        now, assignment_id = utc_now(), new_id("asg")
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                pg_insert(V2ProjectMembership)
                .values(
                    project_id=invitation["project_id"],
                    actor_id=actor_id,
                    project_role="reviewer",
                    created_at=now,
                )
                .on_conflict_do_nothing(index_elements=[V2ProjectMembership.project_id, V2ProjectMembership.actor_id])
            )
            connection.execute(
                pg_insert(V2ReviewAssignment)
                .values(
                    assignment_id=assignment_id,
                    project_id=invitation["project_id"],
                    job_id=invitation["job_id"],
                    reviewer_id=actor_id,
                    invitation_id=invitation["invitation_id"],
                    status="assigned",
                    assigned_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[V2ReviewAssignment.job_id, V2ReviewAssignment.reviewer_id],
                    set_={"status": "assigned", "invitation_id": invitation["invitation_id"]},
                )
            )
            connection.execute(
                update(V2ProjectInvitation)
                .where(V2ProjectInvitation.invitation_id == invitation["invitation_id"])
                .values(status="accepted", accepted_by=actor_id, responded_at=now)
            )
        return self.assignment(invitation["job_id"], actor_id) or {}

    def decline_invitation(self, raw_token: str, actor_id: str) -> dict[str, Any]:
        invitation = self.get_invitation(raw_token)
        if not invitation or invitation["status"] != "pending":
            raise ValueError("Invitation is invalid, expired, or already used")
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                update(V2ProjectInvitation)
                .where(V2ProjectInvitation.invitation_id == invitation["invitation_id"])
                .values(status="declined", accepted_by=actor_id, responded_at=utc_now())
            )
        invitation["status"] = "declined"
        invitation["accepted_by"] = actor_id
        return invitation

    def revoke_invitation(self, project_id: str, invitation_id: str) -> bool:
        with self._write_lock(), self._connect() as connection:
            row = (
                connection.execute(
                    select(V2ProjectInvitation.status).where(
                        V2ProjectInvitation.project_id == project_id,
                        V2ProjectInvitation.invitation_id == invitation_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if not row or row["status"] != "pending":
                return False
            connection.execute(
                update(V2ProjectInvitation)
                .where(V2ProjectInvitation.invitation_id == invitation_id)
                .values(status="revoked", responded_at=utc_now())
            )
        return True

    def list_invitations(self, project_id: str, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = (
                connection.execute(
                    select(
                        V2ProjectInvitation.invitation_id,
                        V2ProjectInvitation.project_id,
                        V2ProjectInvitation.job_id,
                        V2ProjectInvitation.email,
                        V2ProjectInvitation.status,
                        V2ProjectInvitation.invited_by,
                        V2ProjectInvitation.accepted_by,
                        V2ProjectInvitation.expires_at,
                        V2ProjectInvitation.created_at,
                        V2ProjectInvitation.responded_at,
                        V2ProjectInvitation.email_delivery_status,
                        V2ProjectInvitation.email_attempts,
                        V2ProjectInvitation.last_email_attempt_at,
                        V2ProjectInvitation.email_sent_at,
                        V2ProjectInvitation.email_error,
                        V2ProjectInvitation.resend_email_id,
                    )
                    .where(V2ProjectInvitation.project_id == project_id, V2ProjectInvitation.job_id == job_id)
                    .order_by(V2ProjectInvitation.created_at.desc())
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def assignment(self, job_id: str, actor_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = (
                connection.execute(
                    select(V2ReviewAssignment.__table__).where(
                        V2ReviewAssignment.job_id == job_id,
                        V2ReviewAssignment.reviewer_id == actor_id,
                        V2ReviewAssignment.status != "revoked",
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    def list_assignments(self, actor_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = (
                connection.execute(
                    select(
                        V2ReviewAssignment.__table__,
                        V2Project.name.label("project_name"),
                        V2ProjectReviewJob.requested_by,
                        V2ProjectReviewJob.topic,
                        V2ProjectReviewJob.created_at.label("review_created_at"),
                        V2ReportVersion.report_version_id,
                        V2ReportVersion.version_number,
                    )
                    .select_from(
                        V2ReviewAssignment.__table__.join(
                            V2Project.__table__, V2Project.project_id == V2ReviewAssignment.project_id
                        )
                        .join(V2ProjectReviewJob.__table__, V2ProjectReviewJob.job_id == V2ReviewAssignment.job_id)
                        .outerjoin(
                            V2ReportVersion.__table__,
                            and_(
                                V2ReportVersion.project_id == V2ReviewAssignment.project_id,
                                V2ReportVersion.job_id == V2ReviewAssignment.job_id,
                            ),
                        )
                    )
                    .where(V2ReviewAssignment.reviewer_id == actor_id)
                    .order_by(V2ReviewAssignment.assigned_at.desc())
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def record_review_submission(
        self,
        project_id: str,
        job_id: str,
        report_version_id: str,
        reviewer_id: str,
        review_type: str,
        decision: str,
        note: str,
        decisions: list[dict[str, Any]],
        reference_checks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        submission_id, now = new_id("sub"), utc_now()
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                pg_insert(V2ReviewSubmission)
                .values(
                    submission_id=submission_id,
                    project_id=project_id,
                    job_id=job_id,
                    report_version_id=report_version_id,
                    reviewer_id=reviewer_id,
                    review_type=review_type,
                    decision=decision,
                    note=note,
                    decisions_json=canonical_json(decisions),
                    reference_checks_json=canonical_json(reference_checks),
                    submitted_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[
                        V2ReviewSubmission.job_id,
                        V2ReviewSubmission.reviewer_id,
                        V2ReviewSubmission.report_version_id,
                    ],
                    set_={
                        "review_type": review_type,
                        "decision": decision,
                        "note": note,
                        "decisions_json": canonical_json(decisions),
                        "reference_checks_json": canonical_json(reference_checks),
                        "submitted_at": now,
                    },
                )
            )
            connection.execute(
                update(V2ReviewAssignment)
                .where(
                    V2ReviewAssignment.job_id == job_id,
                    V2ReviewAssignment.reviewer_id == reviewer_id,
                )
                .values(status="submitted", submitted_at=now)
            )
            row = (
                connection.execute(
                    select(V2ReviewSubmission.__table__).where(
                        V2ReviewSubmission.job_id == job_id,
                        V2ReviewSubmission.reviewer_id == reviewer_id,
                        V2ReviewSubmission.report_version_id == report_version_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        if not row:
            return {}
        value = dict(row)
        value["decisions"] = _loads(value.pop("decisions_json"), [])
        value["reference_checks"] = _loads(value.pop("reference_checks_json"), [])
        return value

    # Versioning
    def link_review_job(
        self,
        project_id: str,
        job_id: str,
        actor_id: str,
        purpose: str,
        topic: str = "",
        max_results: int = 20,
        conversation_id: str | None = None,
    ) -> None:
        project = self.get_project(project_id)
        try:
            with self._write_lock(), self._connect() as connection:
                connection.execute(
                    pg_insert(V2ProjectReviewJob).values(
                        project_id=project_id,
                        job_id=job_id,
                        conversation_id=conversation_id,
                        requested_by=actor_id,
                        parent_report_version_id=project.get("active_report_version_id") if project else None,
                        purpose=purpose,
                        topic=topic,
                        max_results=max_results,
                        status="queued",
                        created_at=utc_now(),
                    )
                )
        except Exception:
            raise

    def update_review_status(self, job_id: str, status: str) -> None:
        with self._write_lock(), self._connect() as connection:
            link = (
                connection.execute(select(V2ProjectReviewJob.__table__).where(V2ProjectReviewJob.job_id == job_id))
                .mappings()
                .one_or_none()
            )
            if not link:
                return
            connection.execute(
                update(V2ProjectReviewJob).where(V2ProjectReviewJob.job_id == job_id).values(status=status)
            )

    def project_for_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = (
                connection.execute(select(V2ProjectReviewJob.__table__).where(V2ProjectReviewJob.job_id == job_id))
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    def delete_review(self, project_id: str, job_id: str) -> dict[str, Any] | None:
        """Delete a project review and all report-version data owned by it."""
        with self._write_lock(), self._connect() as connection:
            review = (
                connection.execute(
                    select(V2ProjectReviewJob.__table__).where(
                        V2ProjectReviewJob.project_id == project_id,
                        V2ProjectReviewJob.job_id == job_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if not review:
                return None

            connection.execute(delete(V2ResearchPlan).where(V2ResearchPlan.job_id == job_id))

            version_rows = (
                connection.execute(
                    select(V2ReportVersion.report_version_id, V2ReportVersion.version_number)
                    .where(V2ReportVersion.project_id == project_id, V2ReportVersion.job_id == job_id)
                    .order_by(V2ReportVersion.version_number.desc())
                )
                .mappings()
                .all()
            )
            version_ids = [str(version["report_version_id"]) for version in version_rows]
            version_id = version_ids[0] if version_ids else None
            replacement = (
                connection.execute(
                    select(V2ReportVersion.report_version_id)
                    .where(V2ReportVersion.project_id == project_id)
                    .where(or_(V2ReportVersion.job_id.is_(None), V2ReportVersion.job_id != job_id))
                    .order_by(V2ReportVersion.created_at.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            replacement_id = replacement["report_version_id"] if replacement else None

            for owned_version_id in version_ids:
                connection.execute(
                    delete(V2MessageCitation).where(
                        or_(
                            V2MessageCitation.report_version_id == owned_version_id,
                            V2MessageCitation.message_id.in_(
                                select(V2Message.message_id).where(V2Message.report_version_id == owned_version_id)
                            ),
                        )
                    )
                )
                connection.execute(delete(V2Message).where(V2Message.report_version_id == owned_version_id))
                connection.execute(delete(V2GapDecision).where(V2GapDecision.report_version_id == owned_version_id))
                connection.execute(delete(V2Gap).where(V2Gap.report_version_id == owned_version_id))
                connection.execute(
                    delete(V2ReviewerFeedback).where(V2ReviewerFeedback.report_version_id == owned_version_id)
                )
                connection.execute(delete(V2Memory).where(V2Memory.report_version_id == owned_version_id))
                connection.execute(
                    delete(V2ActionProposal).where(
                        or_(
                            V2ActionProposal.base_report_version_id == owned_version_id,
                            V2ActionProposal.result_report_version_id == owned_version_id,
                            V2ActionProposal.executed_job_id == job_id,
                        )
                    )
                )
                connection.execute(
                    update(V2Conversation)
                    .where(V2Conversation.active_report_version_id == owned_version_id)
                    .values(active_report_version_id=replacement_id)
                )
                connection.execute(
                    update(V2ReportVersion)
                    .where(V2ReportVersion.parent_report_version_id == owned_version_id)
                    .values(parent_report_version_id=None)
                )
                connection.execute(
                    update(V2ProjectReviewJob)
                    .where(V2ProjectReviewJob.parent_report_version_id == owned_version_id)
                    .values(parent_report_version_id=None)
                )
                connection.execute(
                    update(V2Project)
                    .where(
                        V2Project.project_id == project_id,
                        V2Project.active_report_version_id == owned_version_id,
                    )
                    .values(active_report_version_id=replacement_id, updated_at=utc_now())
                )

            connection.execute(delete(V2ReviewSubmission).where(V2ReviewSubmission.job_id == job_id))
            connection.execute(delete(V2ReviewAssignment).where(V2ReviewAssignment.job_id == job_id))
            connection.execute(delete(V2ProjectInvitation).where(V2ProjectInvitation.job_id == job_id))
            connection.execute(delete(V2ActionProposal).where(V2ActionProposal.executed_job_id == job_id))
            connection.execute(
                delete(V2ReportVersion).where(
                    V2ReportVersion.project_id == project_id, V2ReportVersion.job_id == job_id
                )
            )
            connection.execute(
                delete(V2ProjectReviewJob).where(
                    V2ProjectReviewJob.project_id == project_id, V2ProjectReviewJob.job_id == job_id
                )
            )
        return {
            "project_id": project_id,
            "job_id": job_id,
            "report_version_id": version_id,
            "report_version_ids": version_ids,
            "replacement_report_version_id": replacement_id,
        }

    def delete_project(self, project_id: str) -> dict[str, Any] | None:
        """Permanently delete a project and all project-scoped product data."""
        with self._write_lock(), self._connect() as connection:
            project = (
                connection.execute(select(V2Project.__table__).where(V2Project.project_id == project_id))
                .mappings()
                .one_or_none()
            )
            if not project:
                return None
            job_rows = (
                connection.execute(select(V2ProjectReviewJob.job_id).where(V2ProjectReviewJob.project_id == project_id))
                .mappings()
                .all()
            )
            job_ids = [row["job_id"] for row in job_rows]

            connection.execute(
                delete(V2MessageCitation).where(
                    or_(
                        V2MessageCitation.project_id == project_id,
                        V2MessageCitation.message_id.in_(
                            select(V2Message.message_id)
                            .select_from(
                                V2Message.__table__.join(
                                    V2Conversation.__table__,
                                    V2Conversation.conversation_id == V2Message.conversation_id,
                                )
                            )
                            .where(V2Conversation.project_id == project_id)
                        ),
                    )
                )
            )
            connection.execute(
                delete(V2Message).where(
                    V2Message.conversation_id.in_(
                        select(V2Conversation.conversation_id).where(V2Conversation.project_id == project_id)
                    )
                )
            )
            connection.execute(delete(V2GapDecision).where(V2GapDecision.project_id == project_id))
            connection.execute(delete(V2ReviewerFeedback).where(V2ReviewerFeedback.project_id == project_id))
            connection.execute(delete(V2Gap).where(V2Gap.project_id == project_id))
            connection.execute(delete(V2ReviewSubmission).where(V2ReviewSubmission.project_id == project_id))
            connection.execute(delete(V2ReviewAssignment).where(V2ReviewAssignment.project_id == project_id))
            connection.execute(delete(V2ProjectInvitation).where(V2ProjectInvitation.project_id == project_id))
            connection.execute(delete(V2ActionProposal).where(V2ActionProposal.project_id == project_id))
            connection.execute(delete(V2Memory).where(V2Memory.project_id == project_id))
            connection.execute(delete(V2Conversation).where(V2Conversation.project_id == project_id))
            connection.execute(delete(V2ReportVersion).where(V2ReportVersion.project_id == project_id))
            connection.execute(delete(V2ProjectReviewJob).where(V2ProjectReviewJob.project_id == project_id))
            connection.execute(delete(V2ProjectMembership).where(V2ProjectMembership.project_id == project_id))
            connection.execute(delete(V2AuditEvent).where(V2AuditEvent.project_id == project_id))
            connection.execute(delete(V2Event).where(V2Event.project_id == project_id))
            connection.execute(delete(V2Project).where(V2Project.project_id == project_id))
        return {"project_id": project_id, "job_ids": job_ids}

    def create_report_version(
        self, project_id: str, report: dict[str, Any], actor_id: str, reason: str, job_id: str | None = None
    ) -> dict[str, Any]:
        now, version_id = utc_now(), new_id("rv")
        report_json = canonical_json(report)
        with self._write_lock(), self._connect() as connection:
            latest = None
            if job_id:
                latest = (
                    connection.execute(
                        select(V2ReportVersion.__table__)
                        .where(V2ReportVersion.project_id == project_id, V2ReportVersion.job_id == job_id)
                        .order_by(V2ReportVersion.version_number.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
            origin_conversation_id = None
            if job_id:
                origin = (
                    connection.execute(
                        select(V2ProjectReviewJob.conversation_id).where(
                            V2ProjectReviewJob.project_id == project_id,
                            V2ProjectReviewJob.job_id == job_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if origin:
                    origin_conversation_id = origin["conversation_id"]

            def pin_originating_conversation(report_version_id: str) -> None:
                if not origin_conversation_id:
                    return
                # A conversation that started this job has no corpus yet. Pin
                # its first completed report so later turns query that job's
                # Qdrant collection. Existing pinned chats stay untouched to
                # preserve their citation scope.
                connection.execute(
                    update(V2Conversation)
                    .where(
                        V2Conversation.conversation_id == origin_conversation_id,
                        V2Conversation.project_id == project_id,
                        V2Conversation.active_report_version_id.is_(None),
                    )
                    .values(active_report_version_id=report_version_id, updated_at=now)
                )

            if latest and latest["report_json"] == report_json:
                pin_originating_conversation(latest["report_version_id"])
                return self._version_row(latest)
            project = (
                connection.execute(select(V2Project.__table__).where(V2Project.project_id == project_id))
                .mappings()
                .one_or_none()
            )
            if not project:
                raise KeyError("project")
            # ``version_number`` is unique per project, not per job. A new
            # review thread therefore must continue the project-wide sequence.
            number = connection.execute(
                select(func.coalesce(func.max(V2ReportVersion.version_number), 0) + 1).where(
                    V2ReportVersion.project_id == project_id
                )
            ).scalar_one()
            parent = latest["report_version_id"] if latest else project["active_report_version_id"]
            corpus = [p.get("paper_id") for p in report.get("papers", [])]
            connection.execute(
                pg_insert(V2ReportVersion).values(
                    report_version_id=version_id,
                    project_id=project_id,
                    job_id=job_id,
                    parent_report_version_id=parent,
                    version_number=number,
                    corpus_hash=content_hash(corpus),
                    report_json=report_json,
                    change_reason=reason,
                    created_by=actor_id,
                    created_at=now,
                )
            )
            connection.execute(
                V2Project.__table__.update()
                .where(V2Project.project_id == project_id)
                .values(active_report_version_id=version_id, updated_at=now)
            )
            pin_originating_conversation(version_id)
            # Conversations are evidence-scoped snapshots. Advancing the
            # project default must never silently retarget an existing chat to
            # a different corpus/job, which would invalidate its citations.
            # New conversations choose the project default in the router.
            connection.execute(
                V2ActionProposal.__table__.update()
                .where(
                    V2ActionProposal.project_id == project_id,
                    V2ActionProposal.status == "proposed",
                    V2ActionProposal.base_report_version_id.is_not(None),
                    V2ActionProposal.base_report_version_id != version_id,
                )
                .values(status="stale")
            )
            connection.execute(
                V2Memory.__table__.update()
                .where(
                    V2Memory.project_id == project_id,
                    V2Memory.status == "active",
                    V2Memory.report_version_id.is_not(None),
                    V2Memory.report_version_id != version_id,
                    V2Memory.memory_type.in_(["conversation_summary", "reviewer_feedback"]),
                )
                .values(status="stale")
            )
        self.audit(
            project_id,
            actor_id,
            "report.version_created",
            "report_version",
            version_id,
            parent,
            version_id,
            {"version_number": number, "change_reason": reason},
        )
        self.event(
            project_id,
            "report.version_created",
            version_id,
            {"version_number": number, "parent_report_version_id": parent},
        )
        return self.get_report_version(project_id, version_id) or {}

    def _version_row(self, row: Any) -> dict[str, Any]:
        value = dict(row)
        value["report"] = _loads(value.pop("report_json"), {})
        return value

    def get_report_version(self, project_id: str, version_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = (
                connection.execute(
                    select(V2ReportVersion.__table__).where(
                        V2ReportVersion.project_id == project_id,
                        V2ReportVersion.report_version_id == version_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._version_row(row) if row else None

    def list_report_versions(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = (
                connection.execute(
                    select(V2ReportVersion.__table__)
                    .where(V2ReportVersion.project_id == project_id)
                    .order_by(V2ReportVersion.version_number.desc())
                )
                .mappings()
                .all()
            )
        return [self._version_row(row) for row in rows]

    # Conversations and citations
    def conversation_context(
        self,
        project_id: str,
        actor_id: str,
        version_id: str | None,
    ) -> dict[str, Any] | None:
        """Load conversation authorization and report validity in one round trip."""

        # PostgreSQL cannot infer a type for a bare bound ``NULL`` in
        # ``:version_id IS NULL OR ...``. Build the appropriate branch in
        # Python so a first conversation can be created before any report
        # version exists.
        report_exists = (
            literal(True)
            if version_id is None
            else select(1)
            .where(
                V2ReportVersion.project_id == project_id,
                V2ReportVersion.report_version_id == version_id,
            )
            .exists()
        )
        with self._connect() as connection:
            row = (
                connection.execute(
                    select(
                        V2Project.project_id,
                        V2Project.active_report_version_id,
                        V2ProjectMembership.project_role,
                        report_exists.label("report_exists"),
                    )
                    .select_from(
                        V2Project.__table__.outerjoin(
                            V2ProjectMembership.__table__,
                            and_(
                                V2ProjectMembership.project_id == V2Project.project_id,
                                V2ProjectMembership.actor_id == actor_id,
                            ),
                        )
                    )
                    .where(V2Project.project_id == project_id)
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    def conversation_access(self, conversation_id: str, actor_id: str) -> dict[str, Any] | None:
        """Load a conversation, its project context and membership together."""

        with self._connect() as connection:
            row = (
                connection.execute(
                    select(
                        V2Conversation.__table__,
                        V2Project.active_report_version_id.label("project_active_report_version_id"),
                        V2ProjectMembership.project_role,
                    )
                    .select_from(
                        V2Conversation.__table__.join(
                            V2Project.__table__, V2Project.project_id == V2Conversation.project_id
                        ).outerjoin(
                            V2ProjectMembership.__table__,
                            and_(
                                V2ProjectMembership.project_id == V2Conversation.project_id,
                                V2ProjectMembership.actor_id == actor_id,
                            ),
                        )
                    )
                    .where(V2Conversation.conversation_id == conversation_id)
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    def get_or_create_conversation(
        self,
        project_id: str,
        actor_id: str,
        version_id: str | None,
        force_new: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        """Reuse an empty conversation and atomically create one when needed.

        Reusing only conversations without messages preserves the existing
        new-chat semantics after a page reload while making repeated clicks and
        retried requests idempotent.
        """

        conversation_id, now = new_id("conv"), utc_now()
        lock_key = f"conversation:{project_id}:{actor_id}:{version_id or ''}"
        with self._write_lock(), self._connect() as connection:
            if self.is_postgres:
                connection.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))
            query = (
                select(V2Conversation.__table__)
                .where(V2Conversation.project_id == project_id, V2Conversation.created_by == actor_id)
                .where(
                    V2Conversation.active_report_version_id.is_(None)
                    if version_id is None
                    else V2Conversation.active_report_version_id == version_id
                )
                .where(~select(1).where(V2Message.conversation_id == V2Conversation.conversation_id).exists())
                .order_by(V2Conversation.updated_at.desc(), V2Conversation.created_at.desc())
                .limit(1)
            )
            existing = None if force_new else connection.execute(query).mappings().one_or_none()
            if existing:
                return dict(existing), True
            row = (
                connection.execute(
                    pg_insert(V2Conversation)
                    .values(
                        conversation_id=conversation_id,
                        project_id=project_id,
                        created_by=actor_id,
                        active_report_version_id=version_id,
                        created_at=now,
                        updated_at=now,
                    )
                    .returning(*V2Conversation.__table__.c)
                )
                .mappings()
                .one()
            )
        return dict(row), False

    def create_conversation(self, project_id: str, actor_id: str, version_id: str | None) -> dict[str, Any]:
        conversation, _ = self.get_or_create_conversation(project_id, actor_id, version_id)
        return conversation

    def list_conversations(self, project_id: str, actor_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = (
                connection.execute(
                    select(V2Conversation.__table__)
                    .where(V2Conversation.project_id == project_id, V2Conversation.created_by == actor_id)
                    .order_by(V2Conversation.updated_at.desc())
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def delete_conversation(self, conversation_id: str, actor_id: str) -> bool:
        with self._write_lock(), self._connect() as connection:
            conversation = (
                connection.execute(
                    select(V2Conversation.__table__).where(
                        V2Conversation.conversation_id == conversation_id, V2Conversation.created_by == actor_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if not conversation:
                return False
            connection.execute(delete(V2ResearchPlan).where(V2ResearchPlan.conversation_id == conversation_id))
            connection.execute(
                delete(V2MessageCitation).where(
                    V2MessageCitation.message_id.in_(
                        select(V2Message.message_id).where(V2Message.conversation_id == conversation_id)
                    )
                )
            )
            connection.execute(delete(V2Message.__table__).where(V2Message.conversation_id == conversation_id))
            connection.execute(
                delete(V2Conversation.__table__).where(V2Conversation.conversation_id == conversation_id)
            )
            return True

    def update_conversation_title(self, conversation_id: str, actor_id: str, title: str) -> dict[str, Any] | None:
        with self._write_lock(), self._connect() as connection:
            row = (
                connection.execute(
                    V2Conversation.__table__.update()
                    .where(V2Conversation.conversation_id == conversation_id, V2Conversation.created_by == actor_id)
                    .values(title=title.strip(), updated_at=utc_now())
                    .returning(*V2Conversation.__table__.c)
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = (
                connection.execute(
                    select(V2Conversation.__table__).where(V2Conversation.conversation_id == conversation_id)
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    def save_user_message(
        self,
        conversation_id: str,
        client_message_id: str,
        user_text: str,
        report_version_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist a user-only turn used by the durable research workflow."""
        now = utc_now()
        with self._write_lock(), self._connect() as connection:
            duplicate = (
                connection.execute(
                    select(V2Message.__table__).where(
                        V2Message.conversation_id == conversation_id,
                        V2Message.client_message_id == client_message_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if duplicate:
                return self._message_row(duplicate, connection)
            message_id = new_id("msg")
            connection.execute(
                pg_insert(V2Message).values(
                    message_id=message_id,
                    conversation_id=conversation_id,
                    client_message_id=client_message_id,
                    role="user",
                    message_type="user_message",
                    text=user_text,
                    report_version_id=report_version_id,
                    created_at=now,
                )
            )
            connection.execute(
                V2Conversation.__table__.update()
                .where(V2Conversation.conversation_id == conversation_id)
                .values(updated_at=now)
            )
            row = (
                connection.execute(select(V2Message.__table__).where(V2Message.message_id == message_id))
                .mappings()
                .one()
            )
        return self._message_row(row, None, [])

    def save_turn(
        self,
        conversation_id: str,
        client_message_id: str,
        user_text: str,
        assistant: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        with self._write_lock(), self._connect() as connection:
            duplicate = (
                connection.execute(
                    select(V2Message.__table__).where(
                        V2Message.conversation_id == conversation_id,
                        V2Message.client_message_id == client_message_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if duplicate:
                assistant_row = (
                    connection.execute(
                        select(V2Message.__table__)
                        .where(
                            V2Message.conversation_id == conversation_id,
                            V2Message.role == "assistant",
                            V2Message.created_at >= duplicate["created_at"],
                        )
                        .order_by(V2Message.created_at)
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                return self._message_row(assistant_row or duplicate, connection), True
            user_message_id = new_id("msg")
            # Keep the pair order deterministic even though both rows are
            # written in one transaction.  Older rows can share the exact
            # same timestamp, so list_messages also applies a role tie-break.
            assistant_created_at = (datetime.fromisoformat(now) + timedelta(microseconds=1)).isoformat()
            connection.execute(
                pg_insert(V2Message).values(
                    message_id=user_message_id,
                    conversation_id=conversation_id,
                    client_message_id=client_message_id,
                    role="user",
                    message_type="user_message",
                    text=user_text,
                    report_version_id=assistant.get("report_version_id"),
                    created_at=now,
                )
            )
            assistant_id = new_id("msg")
            connection.execute(
                pg_insert(V2Message).values(
                    message_id=assistant_id,
                    conversation_id=conversation_id,
                    client_message_id=None,
                    role="assistant",
                    message_type=assistant["message_type"],
                    text=assistant["text"],
                    report_version_id=assistant.get("report_version_id"),
                    content_scope=assistant.get("content_scope"),
                    limitations_json=canonical_json(assistant.get("limitations", [])),
                    context_artifact_ids_json=canonical_json(assistant.get("context_artifact_ids", [])),
                    memory_ids_used_json=canonical_json(assistant.get("memory_ids_used", [])),
                    created_at=assistant_created_at,
                )
            )
            for citation in assistant.get("citations", []):
                connection.execute(
                    pg_insert(V2MessageCitation).values(
                        citation_id=new_id("cit"),
                        message_id=assistant_id,
                        project_id=citation["project_id"],
                        report_version_id=citation["report_version_id"],
                        paper_id=citation["paper_id"],
                        evidence_id=citation.get("evidence_id"),
                        quote=citation.get("quote", ""),
                        source_url=citation.get("source_url", ""),
                        valid=int(citation.get("valid", False)),
                        created_at=now,
                    )
                )
            connection.execute(
                V2Conversation.__table__.update()
                .where(V2Conversation.conversation_id == conversation_id)
                .values(updated_at=now)
            )
            row = (
                connection.execute(select(V2Message.__table__).where(V2Message.message_id == assistant_id))
                .mappings()
                .one()
            )
        return self._message_row(row, None, assistant.get("citations", [])), False

    def create_assistant_message(
        self,
        conversation_id: str,
        text: str,
        report_version_id: str | None = None,
        message_type: str = "final_report",
        client_message_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Persist an idempotent assistant report message in a conversation."""
        now = utc_now()
        with self._write_lock(), self._connect() as connection:
            identity_filters = (
                V2Message.client_message_id == client_message_id
                if client_message_id
                else and_(
                    V2Message.message_type == message_type,
                    V2Message.report_version_id == report_version_id,
                )
            )
            existing = (
                connection.execute(
                    select(V2Message.__table__)
                    .where(
                        V2Message.conversation_id == conversation_id,
                        V2Message.role == "assistant",
                        identity_filters,
                    )
                    .order_by(V2Message.created_at.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if existing:
                return self._message_row(existing, connection)
            message_id = new_id("msg")
            connection.execute(
                pg_insert(V2Message).values(
                    message_id=message_id,
                    conversation_id=conversation_id,
                    client_message_id=client_message_id,
                    role="assistant",
                    message_type=message_type,
                    text=text,
                    report_version_id=report_version_id,
                    content_scope="report",
                    limitations_json="[]",
                    context_artifact_ids_json="[]",
                    memory_ids_used_json="[]",
                    created_at=now,
                )
            )
            connection.execute(
                V2Conversation.__table__.update()
                .where(V2Conversation.conversation_id == conversation_id)
                .values(updated_at=now, active_report_version_id=report_version_id)
            )
            row = (
                connection.execute(select(V2Message.__table__).where(V2Message.message_id == message_id))
                .mappings()
                .one()
            )
        return self._message_row(row, None, [])

    def _message_row(
        self,
        row: Any,
        connection: Any | None = None,
        citations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        value = dict(row)
        for field in ("limitations_json", "context_artifact_ids_json", "memory_ids_used_json"):
            value[field.removesuffix("_json")] = _loads(value.pop(field), [])
        if citations is None:
            owns = connection is None
            connection = connection or self._connect()
            rows = (
                connection.execute(
                    select(V2MessageCitation.__table__).where(V2MessageCitation.message_id == value["message_id"])
                )
                .mappings()
                .all()
            )
            citations = [dict(item) for item in rows]
            if owns:
                connection.close()
        value["citations"] = citations
        return value

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = (
                connection.execute(
                    select(V2Message.__table__)
                    .where(V2Message.conversation_id == conversation_id)
                    .order_by(
                        V2Message.created_at,
                        case((V2Message.role == "user", 0), else_=1),
                        V2Message.message_id,
                    )
                )
                .mappings()
                .all()
            )
            return [self._message_row(row, connection) for row in rows]

    # Memory
    def create_memory(self, data: dict[str, Any]) -> dict[str, Any]:
        memory_id, now = new_id("mem"), utc_now()
        expires_at = None
        if data.get("ttl_seconds"):
            expires_at = (datetime.now(UTC) + timedelta(seconds=data["ttl_seconds"])).isoformat()
        dependency = content_hash({"evidence": data.get("evidence_ids", []), "version": data.get("report_version_id")})
        with self._write_lock(), self._connect() as connection:
            row = (
                connection.execute(
                    pg_insert(V2Memory)
                    .values(
                        memory_id=memory_id,
                        scope="session" if data.get("conversation_id") else "project",
                        project_id=data["project_id"],
                        conversation_id=data.get("conversation_id"),
                        memory_type=data["memory_type"],
                        content_json=canonical_json(data["content"]),
                        evidence_ids_json=canonical_json(data.get("evidence_ids", [])),
                        report_version_id=data.get("report_version_id"),
                        dependency_hash=dependency,
                        status="proposed",
                        created_by=data["created_by"],
                        confirmed_by=None,
                        supersedes_memory_id=None,
                        created_at=now,
                        expires_at=expires_at,
                        deleted_at=None,
                    )
                    .returning(*V2Memory.__table__.c)
                )
                .mappings()
                .one()
            )
        return self._memory_row(row)

    def _memory_row(self, row: Any) -> dict[str, Any]:
        value = dict(row)
        value["content"] = _loads(value.pop("content_json"), {})
        value["evidence_ids"] = _loads(value.pop("evidence_ids_json"), [])
        return value

    def get_memory(self, project_id: str, memory_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = (
                connection.execute(
                    select(V2Memory.__table__).where(
                        V2Memory.project_id == project_id,
                        V2Memory.memory_id == memory_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._memory_row(row) if row else None

    def list_memories(self, project_id: str, include_inactive: bool = True) -> list[dict[str, Any]]:
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                update(V2Memory)
                .where(
                    V2Memory.project_id == project_id,
                    V2Memory.status.in_(["proposed", "active"]),
                    V2Memory.expires_at.is_not(None),
                    V2Memory.expires_at <= utc_now(),
                )
                .values(status="expired")
            )
            query = select(V2Memory.__table__).where(V2Memory.project_id == project_id, V2Memory.deleted_at.is_(None))
            if not include_inactive:
                query = query.where(V2Memory.status == "active")
            rows = connection.execute(query.order_by(V2Memory.created_at.desc())).mappings().all()
        return [self._memory_row(row) for row in rows]

    def confirm_memory(self, project_id: str, memory_id: str, actor_id: str) -> dict[str, Any] | None:
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                update(V2Memory)
                .where(
                    V2Memory.project_id == project_id,
                    V2Memory.memory_id == memory_id,
                    V2Memory.status == "proposed",
                )
                .values(status="active", confirmed_by=actor_id)
            )
        return self.get_memory(project_id, memory_id)

    def supersede_memory(
        self, old: dict[str, Any], actor_id: str, content: dict[str, Any], evidence_ids: list[str]
    ) -> dict[str, Any]:
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                update(V2Memory).where(V2Memory.memory_id == old["memory_id"]).values(status="superseded")
            )
        new_memory = self.create_memory(
            {
                "project_id": old["project_id"],
                "conversation_id": old["conversation_id"],
                "memory_type": old["memory_type"],
                "content": content,
                "evidence_ids": evidence_ids,
                "report_version_id": old["report_version_id"],
                "created_by": actor_id,
            }
        )
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                update(V2Memory)
                .where(V2Memory.memory_id == new_memory["memory_id"])
                .values(supersedes_memory_id=old["memory_id"])
            )
        return self.get_memory(old["project_id"], new_memory["memory_id"]) or new_memory

    def delete_memory(self, project_id: str, memory_id: str) -> bool:
        with self._write_lock(), self._connect() as connection:
            result = connection.execute(
                update(V2Memory)
                .where(
                    V2Memory.project_id == project_id,
                    V2Memory.memory_id == memory_id,
                    V2Memory.deleted_at.is_(None),
                )
                .values(status="deleted", deleted_at=utc_now())
            )
        return result.rowcount > 0

    # Research plans
    def create_research_plan(self, data: dict[str, Any]) -> dict[str, Any]:
        plan_id, now = new_id("plan"), utc_now()
        with self._write_lock(), self._connect() as connection:
            row = (
                connection.execute(
                    pg_insert(V2ResearchPlan)
                    .values(
                        plan_id=plan_id,
                        project_id=data["project_id"],
                        conversation_id=data.get("conversation_id"),
                        prompt=data["prompt"],
                        normalized_question=data["normalized_question"],
                        sub_queries_json=canonical_json(data["sub_queries"]),
                        sources_json=canonical_json(data["sources"]),
                        selection_criteria_json=canonical_json(data.get("selection_criteria", [])),
                        status="proposed",
                        created_by=data["created_by"],
                        approved_by=None,
                        approved_at=None,
                        job_id=None,
                        created_at=now,
                    )
                    .returning(*V2ResearchPlan.__table__.c)
                )
                .mappings()
                .one()
            )
        return self._research_plan_row(row)

    def _research_plan_row(self, row: Any) -> dict[str, Any]:
        value = dict(row)
        for field in ("sub_queries_json", "sources_json", "selection_criteria_json"):
            value[field.removesuffix("_json")] = _loads(value.pop(field), [])
        return value

    def get_research_plan(self, project_id: str, plan_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = (
                connection.execute(
                    select(V2ResearchPlan.__table__).where(
                        V2ResearchPlan.project_id == project_id,
                        V2ResearchPlan.plan_id == plan_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._research_plan_row(row) if row else None

    def approve_research_plan(
        self, project_id: str, plan_id: str, actor_id: str, sub_queries: list[str], sources: list[str]
    ) -> dict[str, Any] | None:
        with self._write_lock(), self._connect() as connection:
            row = (
                connection.execute(
                    select(V2ResearchPlan.__table__)
                    .where(V2ResearchPlan.project_id == project_id, V2ResearchPlan.plan_id == plan_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if not row or row["status"] != "proposed":
                return None
            connection.execute(
                update(V2ResearchPlan)
                .where(V2ResearchPlan.plan_id == plan_id)
                .values(
                    sub_queries_json=canonical_json(sub_queries),
                    sources_json=canonical_json(sources),
                    status="approved",
                    approved_by=actor_id,
                    approved_at=utc_now(),
                )
            )
        return self.get_research_plan(project_id, plan_id)

    def attach_research_plan_job(self, project_id: str, plan_id: str, job_id: str) -> None:
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                update(V2ResearchPlan)
                .where(V2ResearchPlan.project_id == project_id, V2ResearchPlan.plan_id == plan_id)
                .values(job_id=job_id)
            )

    # Actions
    def create_action(self, data: dict[str, Any]) -> dict[str, Any]:
        action_id, now = new_id("act"), utc_now()
        with self._write_lock(), self._connect() as connection:
            row = (
                connection.execute(
                    pg_insert(V2ActionProposal)
                    .values(
                        action_id=action_id,
                        project_id=data["project_id"],
                        conversation_id=data.get("conversation_id"),
                        base_report_version_id=data.get("base_report_version_id"),
                        action_type=data["action_type"],
                        parameters_json=canonical_json(data["parameters"]),
                        reason=data["reason"],
                        source_feedback_id=data.get("source_feedback_id"),
                        external_source_system=data.get("external_source_system"),
                        external_source_id=data.get("external_source_id"),
                        acceptance_criteria_json=canonical_json(data.get("acceptance_criteria", [])),
                        estimated_impact_json=canonical_json(data["estimated_impact"]),
                        status="proposed",
                        proposed_by=data["proposed_by"],
                        approved_by=None,
                        approved_at=None,
                        idempotency_key=None,
                        approval_payload_hash=None,
                        executed_job_id=None,
                        result_report_version_id=None,
                        result_artifact_ids_json="[]",
                        failure_code=None,
                        created_at=now,
                        completed_at=None,
                    )
                    .returning(*V2ActionProposal.__table__.c)
                )
                .mappings()
                .one()
            )
        return self._action_row(row)

    def find_external_action(self, *, project_id: str, source_system: str, source_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = (
                connection.execute(
                    select(V2ActionProposal.__table__).where(
                        V2ActionProposal.project_id == project_id,
                        V2ActionProposal.external_source_system == source_system,
                        V2ActionProposal.external_source_id == source_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._action_row(row) if row else None

    def create_external_action(self, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Atomically create a core-owned draft for one external immutable source."""

        existing = self.find_external_action(
            project_id=data["project_id"],
            source_system=data["external_source_system"],
            source_id=data["external_source_id"],
        )
        if existing is not None:
            return existing, False
        action_id, now = new_id("act"), utc_now()
        insert = pg_insert(V2ActionProposal).values(
            action_id=action_id,
            project_id=data["project_id"],
            conversation_id=data.get("conversation_id"),
            base_report_version_id=data.get("base_report_version_id"),
            action_type=data["action_type"],
            parameters_json=canonical_json(data["parameters"]),
            reason=data["reason"],
            source_feedback_id=data.get("source_feedback_id"),
            external_source_system=data["external_source_system"],
            external_source_id=data["external_source_id"],
            acceptance_criteria_json=canonical_json(data.get("acceptance_criteria", [])),
            estimated_impact_json=canonical_json(data["estimated_impact"]),
            status="proposed",
            proposed_by=data["proposed_by"],
            approved_by=None,
            approved_at=None,
            idempotency_key=None,
            approval_payload_hash=None,
            executed_job_id=None,
            result_report_version_id=None,
            result_artifact_ids_json="[]",
            failure_code=None,
            created_at=now,
            completed_at=None,
        )
        statement = insert.on_conflict_do_nothing(
            index_elements=[
                V2ActionProposal.project_id,
                V2ActionProposal.external_source_system,
                V2ActionProposal.external_source_id,
            ],
            index_where=(
                V2ActionProposal.external_source_system.is_not(None) & V2ActionProposal.external_source_id.is_not(None)
            ),
        ).returning(*V2ActionProposal.__table__.c)
        with self._write_lock(), self._connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        if row is not None:
            return self._action_row(row), True
        existing = self.find_external_action(
            project_id=data["project_id"],
            source_system=data["external_source_system"],
            source_id=data["external_source_id"],
        )
        if existing is None:
            raise RuntimeError("external action conflict did not resolve to a persisted row")
        return existing, False

    def _action_row(self, row: Any) -> dict[str, Any]:
        value = dict(row)
        for field in (
            "parameters_json",
            "acceptance_criteria_json",
            "estimated_impact_json",
            "result_artifact_ids_json",
        ):
            value[field.removesuffix("_json")] = _loads(
                value.pop(field), {} if field == "estimated_impact_json" else []
            )
        return value

    def get_action(self, action_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = (
                connection.execute(select(V2ActionProposal.__table__).where(V2ActionProposal.action_id == action_id))
                .mappings()
                .one_or_none()
            )
        return self._action_row(row) if row else None

    def decide_action(
        self, action_id: str, actor_id: str, decision: str, idempotency_key: str | None, payload: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        payload_hash = content_hash(payload)
        with self._write_lock(), self._connect() as connection:
            row = (
                connection.execute(select(V2ActionProposal.__table__).where(V2ActionProposal.action_id == action_id))
                .mappings()
                .one_or_none()
            )
            if not row:
                return None, "not_found"
            current = self._action_row(row)
            if current["status"] != "proposed":
                if decision == "approved" and current.get("idempotency_key") == idempotency_key:
                    if current.get("approval_payload_hash") == payload_hash:
                        return current, None
                    return current, "duplicate_key"
                return current, "invalid_transition"
            project = (
                connection.execute(
                    select(V2Project.active_report_version_id).where(V2Project.project_id == current["project_id"])
                )
                .mappings()
                .one_or_none()
            )
            if (
                current["base_report_version_id"]
                and project
                and current["base_report_version_id"] != project["active_report_version_id"]
            ):
                connection.execute(
                    update(V2ActionProposal).where(V2ActionProposal.action_id == action_id).values(status="stale")
                )
                current["status"] = "stale"
                return current, "stale"
            if decision == "approved":
                connection.execute(
                    update(V2ActionProposal)
                    .where(V2ActionProposal.action_id == action_id)
                    .values(
                        status="approved",
                        approved_by=actor_id,
                        approved_at=utc_now(),
                        idempotency_key=idempotency_key,
                        approval_payload_hash=payload_hash,
                    )
                )
            else:
                connection.execute(
                    update(V2ActionProposal)
                    .where(V2ActionProposal.action_id == action_id)
                    .values(status=decision, failure_code=payload.get("reason"))
                )
        return self.get_action(action_id), None

    def update_action_result(
        self,
        action_id: str,
        status: str,
        job_id: str | None = None,
        version_id: str | None = None,
        failure: str | None = None,
    ) -> dict[str, Any] | None:
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                update(V2ActionProposal)
                .where(V2ActionProposal.action_id == action_id)
                .values(
                    status=status,
                    executed_job_id=func.coalesce(literal(job_id), V2ActionProposal.executed_job_id),
                    result_report_version_id=func.coalesce(
                        literal(version_id), V2ActionProposal.result_report_version_id
                    ),
                    failure_code=failure,
                    completed_at=utc_now() if status in {"completed", "failed", "cancelled"} else None,
                )
            )
        return self.get_action(action_id)

    # Gaps, feedback, audit, events
    def upsert_gaps_from_report(self, project_id: str, version_id: str, report: dict[str, Any]) -> list[dict[str, Any]]:
        papers = report.get("papers", [])
        now = utc_now()
        with self._write_lock(), self._connect() as connection:
            for raw in report.get("potential_gaps", []):
                raw_gap_id = raw.get("gap_id") or new_id("gap")
                existing_version = connection.execute(
                    select(V2Gap.report_version_id).where(V2Gap.gap_id == raw_gap_id)
                ).scalar_one_or_none()
                gap_id = (
                    f"{raw_gap_id}_{version_id}"
                    if existing_version is not None and existing_version != version_id
                    else raw_gap_id
                )
                coverage = raw.get("coverage", [])
                present = sum(1 for item in coverage if item.get("mentioned") is True)
                not_reported = sum(1 for item in coverage if item.get("mentioned") is False)
                unknown = max(0, len(papers) - len(coverage))
                connection.execute(
                    pg_insert(V2Gap)
                    .values(
                        gap_id=gap_id,
                        project_id=project_id,
                        report_version_id=version_id,
                        gap_type=raw.get("gap_type", "topical"),
                        scoped_statement=raw.get("scope_statement", raw.get("aspect", "")),
                        status=(
                            "contradicted"
                            if raw.get("counterevidence_paper_ids")
                            else "supported_in_searched_corpus"
                            if raw.get("countersearch_performed")
                            else "candidate"
                        ),
                        corpus_size=len(papers),
                        present_count=present,
                        not_reported_count=not_reported,
                        unknown_count=unknown,
                        source_scope="multi_source",
                        content_scope="abstract",
                        coverage_json=canonical_json(coverage),
                        counterevidence_paper_ids_json=canonical_json(raw.get("counterevidence_paper_ids", [])),
                        confidence=raw.get("confidence"),
                        counter_search_query=raw.get("counter_search_query"),
                        reviewer_rationale=raw.get("reviewer_rationale"),
                        verification_status=raw.get("verification_status", "needs_counter_search"),
                        countersearch_report_version_id=None,
                        evidence_score=raw.get("evidence_score"),
                        novelty_score=raw.get("novelty_score"),
                        feasibility_score=raw.get("feasibility_score"),
                        quality_score=raw.get("quality_score"),
                        suggested_method=raw.get("suggested_method"),
                        falsification_condition=raw.get("falsification_condition"),
                        source_type=raw.get("source_type"),
                        created_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=[V2Gap.gap_id])
                )
        return self.list_gaps(project_id, version_id)

    def _gap_row(self, row: Any) -> dict[str, Any]:
        value = dict(row)
        value["coverage"] = _loads(value.pop("coverage_json"), [])
        value["counterevidence_paper_ids"] = _loads(value.pop("counterevidence_paper_ids_json"), [])
        return value

    def list_gaps(self, project_id: str, version_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            query = select(V2Gap.__table__).where(V2Gap.project_id == project_id)
            if version_id:
                query = query.where(V2Gap.report_version_id == version_id)
            rows = connection.execute(query.order_by(V2Gap.created_at)).mappings().all()
        return [self._gap_row(row) for row in rows]

    def get_gap(self, gap_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(select(V2Gap.__table__).where(V2Gap.gap_id == gap_id)).mappings().one_or_none()
        return self._gap_row(row) if row else None

    def complete_gap_countersearch(
        self, gap_id: str, report_version_id: str, counterevidence_paper_ids: list[str]
    ) -> dict[str, Any] | None:
        status = "contradicted" if counterevidence_paper_ids else "supported_in_searched_corpus"
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                update(V2Gap)
                .where(V2Gap.gap_id == gap_id)
                .values(
                    report_version_id=report_version_id,
                    status=status,
                    counterevidence_paper_ids_json=canonical_json(counterevidence_paper_ids),
                    verification_status="reviewed",
                    countersearch_report_version_id=report_version_id,
                )
            )
        return self.get_gap(gap_id)

    def save_gap_review(self, gap: dict[str, Any], actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        decision_id, feedback_id, memory_id, now = new_id("gdec"), new_id("fb"), new_id("mem"), utc_now()
        status_map = {
            "approve": "reviewer_approved",
            "narrow": "reviewer_narrowed",
            "reject": "reviewer_rejected",
            "request_more_evidence": "insufficient_coverage",
        }
        requested = "countersearch" if payload["verdict"] == "request_more_evidence" else "none"
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                pg_insert(V2GapDecision).values(
                    decision_id=decision_id,
                    gap_id=gap["gap_id"],
                    project_id=gap["project_id"],
                    report_version_id=gap["report_version_id"],
                    reviewer_id=actor_id,
                    verdict=payload["verdict"],
                    revised_statement=payload.get("revised_statement"),
                    note=payload.get("note", ""),
                    reviewed_at=now,
                )
            )
            connection.execute(
                update(V2Gap)
                .where(V2Gap.gap_id == gap["gap_id"])
                .values(
                    status=status_map[payload["verdict"]],
                    scoped_statement=func.coalesce(payload.get("revised_statement"), V2Gap.scoped_statement),
                )
            )
            connection.execute(
                pg_insert(V2ReviewerFeedback).values(
                    feedback_id=feedback_id,
                    project_id=gap["project_id"],
                    report_version_id=gap["report_version_id"],
                    source_decision_id=decision_id,
                    target_type="gap",
                    target_id=gap["gap_id"],
                    verdict=payload["verdict"],
                    note=payload.get("note", ""),
                    revised_text=payload.get("revised_statement"),
                    requested_action=requested,
                    status="received",
                    action_id=None,
                    memory_id=memory_id,
                    created_at=now,
                    acknowledged_at=None,
                )
            )
            connection.execute(
                pg_insert(V2Memory).values(
                    memory_id=memory_id,
                    scope="project",
                    project_id=gap["project_id"],
                    conversation_id=None,
                    memory_type="reviewer_feedback",
                    content_json=canonical_json(
                        {
                            "feedback_id": feedback_id,
                            "gap_id": gap["gap_id"],
                            "verdict": payload["verdict"],
                            "note": payload.get("note", ""),
                        }
                    ),
                    evidence_ids_json=canonical_json([gap["gap_id"]]),
                    report_version_id=gap["report_version_id"],
                    dependency_hash=None,
                    status="proposed",
                    created_by=actor_id,
                    confirmed_by=None,
                    supersedes_memory_id=None,
                    created_at=now,
                    expires_at=None,
                    deleted_at=None,
                )
            )
        return {
            "decision_id": decision_id,
            "feedback_id": feedback_id,
            "memory_id": memory_id,
            "gap": self.get_gap(gap["gap_id"]),
        }

    def list_feedback(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = (
                connection.execute(
                    select(V2ReviewerFeedback.__table__)
                    .where(V2ReviewerFeedback.project_id == project_id)
                    .order_by(V2ReviewerFeedback.created_at.desc())
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def create_reviewer_feedback(
        self,
        project_id: str,
        report_version_id: str,
        actor_id: str,
        target_type: str,
        target_id: str,
        verdict: str,
        note: str,
        requested_action: str,
    ) -> dict[str, Any]:
        feedback_id, memory_id, now = new_id("fb"), new_id("mem"), utc_now()
        source_decision_id = new_id("decision")
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                pg_insert(V2ReviewerFeedback).values(
                    feedback_id=feedback_id,
                    project_id=project_id,
                    report_version_id=report_version_id,
                    source_decision_id=source_decision_id,
                    target_type=target_type,
                    target_id=target_id,
                    verdict=verdict,
                    note=note,
                    revised_text=None,
                    requested_action=requested_action,
                    status="received",
                    action_id=None,
                    memory_id=memory_id,
                    created_at=now,
                    acknowledged_at=None,
                )
            )
            connection.execute(
                pg_insert(V2Memory).values(
                    memory_id=memory_id,
                    scope="project",
                    project_id=project_id,
                    conversation_id=None,
                    memory_type="reviewer_feedback",
                    content_json=canonical_json(
                        {
                            "feedback_id": feedback_id,
                            "target_type": target_type,
                            "target_id": target_id,
                            "verdict": verdict,
                            "note": note,
                            "requested_action": requested_action,
                        }
                    ),
                    evidence_ids_json=canonical_json([target_id]),
                    report_version_id=report_version_id,
                    dependency_hash=None,
                    status="proposed",
                    created_by=actor_id,
                    confirmed_by=None,
                    supersedes_memory_id=None,
                    created_at=now,
                    expires_at=None,
                    deleted_at=None,
                )
            )
        return {
            "feedback_id": feedback_id,
            "memory_id": memory_id,
            "source_decision_id": source_decision_id,
            "project_id": project_id,
            "report_version_id": report_version_id,
            "target_type": target_type,
            "target_id": target_id,
            "verdict": verdict,
            "requested_action": requested_action,
            "status": "received",
        }

    def audit(
        self,
        project_id: str,
        actor_id: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        base_version_id: str | None = None,
        result_version_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._write_lock(), self._connect() as connection:
            connection.execute(
                pg_insert(V2AuditEvent).values(
                    audit_id=new_id("audit"),
                    project_id=project_id,
                    actor_id=actor_id,
                    event_type=event_type,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    base_version_id=base_version_id,
                    result_version_id=result_version_id,
                    correlation_id=new_id("corr"),
                    metadata_json=canonical_json(metadata or {}),
                    created_at=utc_now(),
                )
            )

    def event(
        self,
        project_id: str,
        event_type: str,
        entity_id: str | None,
        data: dict[str, Any],
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        with self._write_lock(), self._connect() as connection:
            sequence = connection.execute(
                select(func.coalesce(func.max(V2Event.sequence), 0) + 1).where(V2Event.project_id == project_id)
            ).scalar_one()
            event = {
                "event_id": new_id("evt"),
                "sequence": sequence,
                "project_id": project_id,
                "conversation_id": conversation_id,
                "event_type": event_type,
                "entity_id": entity_id,
                "data": data,
                "created_at": utc_now(),
            }
            connection.execute(
                pg_insert(V2Event).values(
                    event_id=event["event_id"],
                    sequence=sequence,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    event_type=event_type,
                    entity_id=entity_id,
                    data_json=canonical_json(data),
                    created_at=event["created_at"],
                )
            )
        return event

    def list_events(self, conversation_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = (
                connection.execute(
                    select(V2Event.__table__)
                    .where(V2Event.conversation_id == conversation_id, V2Event.sequence > after_sequence)
                    .order_by(V2Event.sequence)
                )
                .mappings()
                .all()
            )
        values = []
        for row in rows:
            value = dict(row)
            value["data"] = _loads(value.pop("data_json"), {})
            values.append(value)
        return values

    def metrics(self) -> dict[str, Any]:
        with self._connect() as connection:
            factual = connection.execute(
                select(func.count()).select_from(V2Message).where(V2Message.message_type == "grounded_answer")
            ).scalar_one()
            cited = connection.execute(
                select(func.count(func.distinct(V2Message.message_id)))
                .select_from(V2Message)
                .join(V2MessageCitation, V2Message.message_id == V2MessageCitation.message_id)
                .where(V2Message.message_type == "grounded_answer", V2MessageCitation.valid == 1)
            ).scalar_one()
            invalid_citations = connection.execute(
                select(func.count()).select_from(V2MessageCitation).where(V2MessageCitation.valid == 0)
            ).scalar_one()
            unconfirmed = connection.execute(
                select(func.count())
                .select_from(V2ActionProposal)
                .where(
                    V2ActionProposal.status.in_(["queued", "running", "completed"]),
                    V2ActionProposal.approved_by.is_(None),
                )
            ).scalar_one()
            stale_applied = connection.execute(
                select(func.count())
                .select_from(V2ActionProposal)
                .where(V2ActionProposal.status == "completed", V2ActionProposal.failure_code == "ACTION_STALE")
            ).scalar_one()
            active_facts = connection.execute(
                select(func.count())
                .select_from(V2Memory)
                .where(
                    V2Memory.memory_type.in_(["decision", "research_scope", "reviewer_feedback"]),
                    V2Memory.status == "active",
                )
            ).scalar_one()
            invalid_facts = connection.execute(
                select(func.count())
                .select_from(V2Memory)
                .where(
                    V2Memory.memory_type.in_(["decision", "research_scope", "reviewer_feedback"]),
                    V2Memory.status == "active",
                    (V2Memory.report_version_id.is_(None) | (V2Memory.evidence_ids_json == "[]")),
                )
            ).scalar_one()
            gaps_reviewed = connection.execute(select(func.count()).select_from(V2GapDecision)).scalar_one()
            full_coverage = connection.execute(
                select(func.count())
                .select_from(V2Gap)
                .where(
                    V2Gap.status.in_(["reviewer_approved", "reviewer_narrowed"]),
                    V2Gap.unknown_count == 0,
                    V2Gap.corpus_size == (V2Gap.present_count + V2Gap.not_reported_count),
                )
            ).scalar_one()
        coverage = cited / factual if factual else 0.0
        return {
            "factual_answers": factual,
            "cited_factual_answers": cited,
            "factual_answer_citation_coverage": coverage,
            "invalid_citations": invalid_citations,
            "unconfirmed_mutations": unconfirmed,
            "stale_actions_applied": stale_applied,
            "active_fact_memories": active_facts,
            "invalid_fact_memories": invalid_facts,
            "gaps_reviewed": gaps_reviewed,
            "approved_gaps_with_full_coverage": full_coverage,
            "mvp2_policy_passed": bool(
                factual
                and coverage == 1.0
                and invalid_citations == 0
                and unconfirmed == 0
                and stale_applied == 0
                and invalid_facts == 0
            ),
        }
