"""S7 boundary adapters.  They are optional and never run on ordinary core paths."""

from sandbox_service.integration.gateway import SandboxGateway, SandboxGatewayOutcome

__all__ = ["PostgresReplayStore", "SandboxGateway", "SandboxGatewayOutcome"]


def __getattr__(name: str):
    # Keep gateway/domain imports usable in lightweight unit-test environments
    # where the optional production PostgreSQL driver is not installed yet.
    if name == "PostgresReplayStore":
        from sandbox_service.integration.postgres_replay import PostgresReplayStore

        return PostgresReplayStore
    raise AttributeError(name)
