import pytest

from sandbox_service.storage.s3 import S3ObjectStore


class _Body:
    def __init__(self, value: bytes) -> None:
        self.value = value
        self.closed = False

    def read(self) -> bytes:
        return self.value

    def close(self) -> None:
        self.closed = True


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.head_calls = 0

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]

    def get_object(self, **kwargs):
        return {"Body": _Body(self.objects[(kwargs["Bucket"], kwargs["Key"])])}

    def delete_object(self, **kwargs):
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)

    def head_bucket(self, **kwargs):
        self.head_calls += 1


@pytest.mark.asyncio
async def test_s3_adapter_is_shared_storage_compatible_and_rejects_unsafe_keys(monkeypatch) -> None:
    client = FakeS3Client()
    monkeypatch.setattr("sandbox_service.storage.s3.boto3.client", lambda *args, **kwargs: client)
    store = S3ObjectStore(
        bucket="sandbox-artifacts",
        endpoint_url="http://object-store.internal:9000",
        access_key_id="access",
        secret_access_key="secret",
    )

    key = await store.put_bytes(
        key="datasets/project-a/dataset-a/data.csv",
        data=b"value\n1\n",
        content_type="text/csv",
    )
    assert key == "datasets/project-a/dataset-a/data.csv"
    assert await store.get_bytes(key=key) == b"value\n1\n"
    await store.healthcheck()
    assert client.head_calls == 1
    await store.delete(key=key)
    assert client.objects == {}

    for unsafe in ("../escape", "..\\escape", "/absolute", "folder/../escape"):
        with pytest.raises(ValueError):
            await store.put_bytes(key=unsafe, data=b"x", content_type="text/plain")
