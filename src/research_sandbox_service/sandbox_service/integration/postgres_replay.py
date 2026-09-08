"""Synchronous atomic replay store for signed service-auth verification."""

from __future__ import annotations

class PostgresReplayStore:
    """Consume HMAC nonces atomically across processes and replicas.

    ``SignedServiceAuth.verify`` is intentionally synchronous, so this narrow
    adapter uses a short-lived psycopg connection rather than leaking async DB
    work into a FastAPI dependency.  The internal gateway traffic is low-volume;
    deployments with higher throughput can supply the same ReplayStore protocol
    backed by Redis or a dedicated synchronous pool.
    """

    def __init__(self, database_url: str, *, connect_timeout_seconds: int = 3) -> None:
        self._dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        self._connect_timeout_seconds = connect_timeout_seconds

    def consume(self, *, key_id: str, nonce: str, expires_at: int, now: int) -> bool:
        # Keep the development/in-memory control plane importable without the
        # optional PostgreSQL driver. Production images install it from the
        # locked control dependency set.
        import psycopg

        with psycopg.connect(
            self._dsn, connect_timeout=self._connect_timeout_seconds
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM sandbox_service_auth_nonces WHERE expires_at <= %s",
                    (now,),
                )
                cursor.execute(
                    """
                    INSERT INTO sandbox_service_auth_nonces (key_id, nonce, expires_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (key_id, nonce) DO NOTHING
                    RETURNING nonce
                    """,
                    (key_id, nonce, expires_at),
                )
                return cursor.fetchone() is not None
