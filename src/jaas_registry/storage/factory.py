"""Builds the configured ObjectStore (storage/base.py) from Settings.storage_backend
— the one place cli.py's cmd_serve and cmd_publish should construct a store, so
the two entrypoints can't drift on backend selection.
"""

from __future__ import annotations

from opentelemetry.trace import Tracer

from jaas_registry.common.config import Settings
from jaas_registry.storage.base import ObjectStore


def build_store(settings: Settings, *, tracer: Tracer | None = None) -> ObjectStore:
    if settings.storage_backend == "s3":
        from jaas_registry.storage.s3_store import S3ObjectStore

        if not settings.storage_s3_bucket:
            raise ValueError(
                "JAAS_STORAGE_S3_BUCKET is required when JAAS_STORAGE_BACKEND=s3"
            )
        return S3ObjectStore(
            bucket=settings.storage_s3_bucket,
            endpoint_url=settings.storage_s3_endpoint_url,
            region_name=settings.storage_s3_region,
            access_key_id=settings.storage_s3_access_key_id,
            secret_access_key=settings.storage_s3_secret_access_key,
            prefix=settings.storage_s3_prefix,
            tracer=tracer,
        )

    from jaas_registry.storage.local_filesystem import LocalFilesystemStore

    return LocalFilesystemStore(settings.storage_root, tracer=tracer)
