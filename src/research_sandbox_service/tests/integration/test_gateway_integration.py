import hashlib
import hmac
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest

# This contract test intentionally crosses the independently packaged service
# boundary and therefore needs the repository root in addition to the sandbox
# package path configured by src/research_sandbox_service/pyproject.toml.
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from sandbox_service.config import SandboxSettings
from sandbox_service.domain.adoption import AdoptionProposal, AdoptionProposalStatus
from sandbox_service.domain.sessions import CreateSandboxSessionRequest
from sandbox_service.integration.adoption_bridge import AdoptionHandOffRejected, AdoptionProposalBridge
from sandbox_service.integration.auth import (
    ContextSnapshotSigner,
    InMemoryReplayStore,
    ServiceAuthError,
    SignedServiceAuth,
)
from sandbox_service.integration.context_mapping import ResearchContextMapper, sandbox_action_metadata
from sandbox_service.integration.gateway import (
    HttpSandboxControlClient,
    SandboxGateway,
    SandboxGatewayRejected,
    SandboxGatewaySettings,
    SandboxServiceUnavailable,
)
from sandbox_service.main import create_app
from tests.fakes import FakeObjectStore

from src.agents.research_sandbox.infrastructure.gateway import (
    BackendSandboxGatewaySettings,
    CoreResearchContextSigner,
    SandboxControlGateway,
)

KEY = b"integration-test-service-auth-key-at-least-32-bytes"
CONTEXT_KEY = b"integration-test-context-auth-key-at-least-32-bytes"


def sign_raw_bff_request(
    *, key: str, method: str, path: str, body: bytes, nonce: str = "raw-body-nonce"
) -> dict[str, str]:
    timestamp = str(int(datetime.now(UTC).timestamp()))
    digest = hashlib.sha256(body).hexdigest()
    project_id = "project-a"
    actor_id = "actor-a"
    correlation_id = "corr-raw-body"
    canonical = "\n".join((method, path, digest, project_id, actor_id, correlation_id, timestamp, nonce))
    return {
        "X-Sandbox-Key-Id": "sandbox-v1",
        "X-Sandbox-Timestamp": timestamp,
        "X-Sandbox-Nonce": nonce,
        "X-Sandbox-Project-Id": project_id,
        "X-Sandbox-Actor-Id": actor_id,
        "X-Correlation-Id": correlation_id,
        "X-Sandbox-Content-SHA256": digest,
        "X-Sandbox-Signature": hmac.new(key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest(),
    }


class DownClient:
    async def create_session(self, **kwargs):
        raise SandboxServiceUnavailable("down")


class CoreSink:
    def __init__(self) -> None:
        self.drafts = []

    async def create_draft(self, proposal, *, actor_id: str, correlation_id: str) -> str:
        self.drafts.append((proposal, actor_id, correlation_id))
        return "core_draft_1"


class CurrentAccess:
    def __init__(self, current: bool = True) -> None:
        self.current = current

    async def is_current_and_authorized(self, **kwargs) -> bool:
        return self.current


def mapper() -> ResearchContextMapper:
    return ResearchContextMapper(snapshot_signer=ContextSnapshotSigner(signing_key=CONTEXT_KEY))


def graphrag_request() -> CreateSandboxSessionRequest:
    return CreateSandboxSessionRequest(
        mode="hypothesis",
        entrypoint="graphrag_answer",
        source_resource_id="answer-1",
        title="Inspect GraphRAG answer",
    )


@pytest.mark.asyncio
async def test_disabled_or_down_sandbox_never_breaks_core_path() -> None:
    snapshot = mapper().graphrag_answer(
        project_id="project-a", answer_id="answer-1", graph_version_id="graph-v1", evidence_refs=[]
    )
    disabled = SandboxGateway(settings=SandboxGatewaySettings(), client=DownClient(), context_mapper=mapper())
    outcome = await disabled.open_session(
        project_id="project-a",
        actor_id="actor-a",
        correlation_id="corr-disabled",
        request=graphrag_request(),
        context_snapshot=snapshot,
    )
    assert outcome.status == "disabled"

    down = SandboxGateway(
        settings=SandboxGatewaySettings(enabled=True, hypothesis_enabled=True),
        client=DownClient(),
        context_mapper=mapper(),
    )
    unavailable = await down.open_session(
        project_id="project-a",
        actor_id="actor-a",
        correlation_id="corr-down",
        request=graphrag_request(),
        context_snapshot=snapshot,
    )
    assert unavailable.status == "unavailable"
    assert unavailable.show_sandbox_action is True


@pytest.mark.asyncio
async def test_stale_or_wrong_project_context_is_rejected_before_service_call() -> None:
    context_mapper = mapper()
    snapshot = context_mapper.graphrag_answer(
        project_id="project-a", answer_id="answer-1", graph_version_id="graph-v1", evidence_refs=[]
    )
    gateway = SandboxGateway(
        settings=SandboxGatewaySettings(enabled=True, hypothesis_enabled=True),
        client=DownClient(),
        context_mapper=context_mapper,
    )

    with pytest.raises(SandboxGatewayRejected):
        await gateway.open_session(
            project_id="project-b",
            actor_id="actor-a",
            correlation_id="corr-wrong-project",
            request=graphrag_request(),
            context_snapshot=snapshot,
        )
    with pytest.raises(SandboxGatewayRejected):
        await gateway.open_session(
            project_id="project-a",
            actor_id="actor-a",
            correlation_id="corr-stale",
            request=graphrag_request(),
            context_snapshot=snapshot.model_copy(update={"graph_version_id": "graph-v2"}),
        )


@pytest.mark.asyncio
async def test_graphrag_mapping_opens_signed_session_through_control_service() -> None:
    context_mapper = mapper()
    service_auth = SignedServiceAuth(signing_key=KEY)
    app = create_app(gateway_service_auth=service_auth, gateway_context_mapper=context_mapper)
    app.state.sandbox_settings = SandboxSettings(
        SANDBOX_ENABLED=True,
        SANDBOX_HYPOTHESIS_ENABLED=True,
    )
    client = HttpSandboxControlClient(
        base_url="http://sandbox.test",
        service_auth=service_auth,
        transport=httpx.ASGITransport(app=app),
    )
    snapshot = context_mapper.graphrag_answer(
        project_id="project-a",
        answer_id="answer-1",
        graph_version_id="graph-v1",
        evidence_refs=[{"evidence_id": "ev-1", "version": "1"}],
        research_question="What is associated with the outcome?",
    )
    gateway = SandboxGateway(
        settings=SandboxGatewaySettings(enabled=True, hypothesis_enabled=True),
        client=client,
        context_mapper=context_mapper,
    )

    outcome = await gateway.open_session(
        project_id="project-a",
        actor_id="actor-a",
        correlation_id="corr-create",
        request=graphrag_request(),
        context_snapshot=snapshot,
    )

    assert outcome.status == "created"
    assert outcome.session and outcome.session.context_hash == snapshot.content_hash
    assert sandbox_action_metadata(snapshot)["action"] == "open_in_sandbox"


@pytest.mark.asyncio
async def test_core_bff_context_signature_is_accepted_by_control_service() -> None:
    """Protect the real core -> control contract, not only the sandbox-side mapper."""

    service_key = KEY.decode("utf-8")
    context_key = CONTEXT_KEY.decode("utf-8")
    service_key_id = "core-service-v1"
    context_key_id = "core-context-v1"
    app = create_app(
        settings=SandboxSettings(
            SANDBOX_ENABLED=True,
            SANDBOX_HYPOTHESIS_ENABLED=True,
            SANDBOX_SERVICE_AUTH_KEY=service_key,
            SANDBOX_SERVICE_AUTH_KEY_ID=service_key_id,
            SANDBOX_CONTEXT_SIGNING_KEY=context_key,
            SANDBOX_CONTEXT_SIGNING_KEY_ID=context_key_id,
        )
    )
    gateway = SandboxControlGateway(
        settings=BackendSandboxGatewaySettings(
            enabled=True,
            demo_mode=False,
            hypothesis_enabled=True,
            graph_overlay_enabled=False,
            data_analysis_enabled=True,
            ai_enabled=False,
            graph_context_enabled=True,
            result_interpretation_enabled=False,
            control_url="http://sandbox.test",
            service_auth_key=service_key,
            service_auth_key_id=service_key_id,
            context_signing_key=context_key,
            context_signing_key_id=context_key_id,
            timeout_seconds=5,
            max_request_bytes=1024 * 1024,
            max_response_bytes=1024 * 1024,
        ),
        transport=httpx.ASGITransport(app=app),
    )
    snapshot = CoreResearchContextSigner(key=context_key, key_id=context_key_id).graphrag_answer(
        project_id="project-a",
        message={
            "message_id": "answer-from-core",
            "report_version_id": "report-v1",
            "citations": [
                {
                    "citation_id": "citation-1",
                    "paper_id": "paper-1",
                    "evidence_id": "evidence-1",
                    "report_version_id": "report-v1",
                    "valid": True,
                }
            ],
            "limitations": ["Abstract-level evidence only."],
        },
    )

    assert str(UUID(snapshot["context_id"])) == snapshot["context_id"]

    response = await gateway.open_session(
        project_id="project-a",
        actor_id="actor-a",
        correlation_id="corr-core-contract",
        session_request={
            "mode": "hypothesis",
            "entrypoint": "graphrag_answer",
            "source_resource_id": "answer-from-core",
            "title": "Hypothesis from grounded answer",
            "initial_question": None,
        },
        context_snapshot=snapshot,
    )

    assert response.status_code == 201, response.content.decode("utf-8")


@pytest.mark.asyncio
async def test_approved_adoption_is_handed_off_only_as_core_draft() -> None:
    sink = CoreSink()
    bridge = AdoptionProposalBridge(sink=sink, revalidator=CurrentAccess())
    proposal = AdoptionProposal(
        project_id="project-a",
        session_id="session-a",
        source_type="hypothesis",
        source_id="hypothesis-a",
        rationale="Reviewer accepted the sandbox draft.",
        requested_by="actor-a",
        status=AdoptionProposalStatus.APPROVED,
    )

    draft_id = await bridge.hand_off(
        project_id="project-a",
        actor_id="actor-a",
        correlation_id="corr-adoption",
        proposal=proposal,
        source_bundle={
            "schema_version": "sandbox_adoption_bundle.v1",
            "source_type": "hypothesis",
            "source_id": "hypothesis-a",
            "base_graph_version_id": None,
        },
    )

    assert draft_id == "core_draft_1"
    assert sink.drafts[0][0].status == "draft"
    with pytest.raises(AdoptionHandOffRejected):
        await AdoptionProposalBridge(sink=sink, revalidator=CurrentAccess(current=False)).hand_off(
            project_id="project-a",
            actor_id="actor-a",
            correlation_id="corr-stale-adoption",
            proposal=proposal,
            source_bundle={
                "schema_version": "sandbox_adoption_bundle.v1",
                "source_type": "hypothesis",
                "source_id": "hypothesis-a",
                "base_graph_version_id": None,
            },
        )


def test_service_auth_supports_key_rotation_and_shared_replay_protection() -> None:
    old_key = b"old-integration-service-key-that-is-at-least-32-bytes"
    new_key = b"new-integration-service-key-that-is-at-least-32-bytes"
    replay_store = InMemoryReplayStore()
    signer = SignedServiceAuth(signing_key=old_key, key_id="old")
    verifier_a = SignedServiceAuth(
        signing_key=new_key,
        key_id="new",
        verification_keys={"old": old_key},
        replay_store=replay_store,
    )
    verifier_b = SignedServiceAuth(
        signing_key=new_key,
        key_id="new",
        verification_keys={"old": old_key},
        replay_store=replay_store,
    )
    body = {"request": {"mode": "hypothesis"}}
    now = datetime.now(UTC)
    headers = signer.sign(
        method="POST",
        path="/internal/v1/gateway/sessions",
        body=body,
        project_id="project-a",
        actor_id="actor-a",
        correlation_id="corr-a",
        now=now,
        nonce="unique-nonce",
    )

    assert verifier_a.verify(
        method="POST",
        path="/internal/v1/gateway/sessions",
        body=body,
        headers=headers,
        now=now,
    ) == ("project-a", "actor-a", "corr-a")
    with pytest.raises(ServiceAuthError, match="replayed"):
        verifier_b.verify(
            method="POST",
            path="/internal/v1/gateway/sessions",
            body=body,
            headers=headers,
            now=now,
        )


def test_context_snapshot_key_rotation_keeps_old_signed_snapshots_verifiable() -> None:
    old_key = b"old-integration-context-key-that-is-at-least-32-bytes"
    new_key = b"new-integration-context-key-that-is-at-least-32-bytes"
    old_mapper = ResearchContextMapper(snapshot_signer=ContextSnapshotSigner(signing_key=old_key, key_id="old-context"))
    snapshot = old_mapper.graphrag_answer(
        project_id="project-a",
        answer_id="answer-1",
        graph_version_id="graph-v1",
        evidence_refs=[],
    )
    rotated_mapper = ResearchContextMapper(
        snapshot_signer=ContextSnapshotSigner(
            signing_key=new_key,
            key_id="new-context",
            verification_keys={"old-context": old_key},
        )
    )

    assert (
        rotated_mapper.verify(
            snapshot,
            project_id="project-a",
            entrypoint=snapshot.source_type,
            source_resource_id="answer-1",
        )
        == snapshot
    )


@pytest.mark.asyncio
async def test_default_control_verifies_exact_bff_bytes_and_rejects_replay() -> None:
    service_key = "integration-bff-service-key-that-is-at-least-32-bytes"
    settings = SandboxSettings(
        SANDBOX_ENABLED=True,
        SANDBOX_DATA_ANALYSIS_ENABLED=True,
        SANDBOX_SERVICE_AUTH_KEY=service_key,
        SANDBOX_CONTEXT_SIGNING_KEY=("integration-bff-context-key-that-is-at-least-32-bytes"),
    )
    app = create_app(settings=settings, object_store=FakeObjectStore())
    path = "/api/v1/projects/project-a/datasets"
    request = httpx.Request(
        "POST",
        "http://sandbox.test" + path,
        files={"file": ("sample.csv", b"outcome,value\n1,2\n", "text/csv")},
        headers={"X-Dataset-Classification": "non_sensitive"},
    )
    body = request.read()
    headers = dict(request.headers)
    headers.update(sign_raw_bff_request(key=service_key, method="POST", path=path, body=body))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://sandbox.test") as client:
        created = await client.post(path, content=body, headers=headers)
        replayed = await client.post(path, content=body, headers=headers)

    assert created.status_code == 201, created.text
    assert replayed.status_code == 401
    assert replayed.json()["detail"]["error_code"] == "SERVICE_AUTH_INVALID"
