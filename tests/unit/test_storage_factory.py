import pytest

from jaas_registry.common.config import Settings
from jaas_registry.storage.factory import build_store
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from jaas_registry.storage.s3_store import S3ObjectStore


def test_defaults_to_local_filesystem_store(tmp_path):
    settings = Settings(storage_root=tmp_path)
    store = build_store(settings)
    assert isinstance(store, LocalFilesystemStore)


def test_s3_backend_requires_bucket():
    settings = Settings(storage_backend="s3")
    with pytest.raises(ValueError, match="JAAS_STORAGE_S3_BUCKET"):
        build_store(settings)


def test_s3_backend_builds_s3_object_store():
    settings = Settings(storage_backend="s3", storage_s3_bucket="jaas-registry-prod")
    store = build_store(settings)
    assert isinstance(store, S3ObjectStore)
    assert store.bucket == "jaas-registry-prod"
