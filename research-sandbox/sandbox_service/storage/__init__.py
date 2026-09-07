"""Object-storage adapters owned by the sandbox service."""

from sandbox_service.storage.local import LocalObjectStore
from sandbox_service.storage.s3 import S3ObjectStore

__all__ = ["LocalObjectStore", "S3ObjectStore"]
