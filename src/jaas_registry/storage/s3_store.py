"""S3-compatible object store — implements storage/base.py's ObjectStore protocol
against any S3-compatible endpoint: OCI Object Storage's S3 Compatibility API,
MinIO, or AWS S3 itself. This is the production backend design.md §1.1.5 and
§9.3.2 always specified; storage/local_filesystem.py remains the local-only
prototype it replaces at deploy time.

Immutability (write_tag_if_absent) uses a conditional PUT (`IfNoneMatch="*"`),
the S3-native equivalent of local_filesystem.py's O_EXCL create — atomic and
race-free on any backend that honors the header. OCI Object Storage's native
API documents if-none-match support on PutObject; this trusts that the S3
Compatibility API forwards it rather than falling back to a check-then-put,
which would reopen the race the local store's O_EXCL avoids. Verify against
the real endpoint before relying on this in production (see deploy/README.md).
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING, Any

from opentelemetry.trace import Tracer

from jaas_registry.common.errors import ErrorCode, JaasError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


def _is_precondition_failed(exc: Any) -> bool:
    response = getattr(exc, "response", {})
    code = response.get("Error", {}).get("Code", "")
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in ("PreconditionFailed", "412") or status == 412


def _is_not_found(exc: Any) -> bool:
    response = getattr(exc, "response", {})
    code = response.get("Error", {}).get("Code", "")
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in ("404", "NoSuchKey", "NotFound") or status == 404


class S3ObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region_name: str = "us-east-1",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        prefix: str = "",
        tracer: Tracer | None = None,
        client: S3Client | None = None,
    ):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._tracer = tracer
        self._client = client or self._build_client(
            endpoint_url=endpoint_url,
            region_name=region_name,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )

    @staticmethod
    def _build_client(
        *,
        endpoint_url: str | None,
        region_name: str,
        access_key_id: str | None,
        secret_access_key: str | None,
    ) -> S3Client:
        import boto3

        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def _span(self, name: str):
        """design.md §10.3: trace storage calls. No-op context manager when no
        tracer is configured, so instrumentation is opt-in, not a hard dependency."""
        if self._tracer is None:
            return nullcontext()
        return self._tracer.start_as_current_span(name)

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def write_blob_if_absent(self, key: str, data: bytes) -> None:
        with self._span("storage.write_blob_if_absent"):
            from botocore.exceptions import ClientError

            try:
                self._client.put_object(
                    Bucket=self.bucket, Key=self._key(key), Body=data, IfNoneMatch="*"
                )
            except ClientError as exc:
                if _is_precondition_failed(exc):
                    return  # content-addressed: same key implies same content
                raise

    def write_tag_if_absent(self, key: str, data: bytes) -> None:
        with self._span("storage.write_tag_if_absent"):
            from botocore.exceptions import ClientError

            try:
                self._client.put_object(
                    Bucket=self.bucket, Key=self._key(key), Body=data, IfNoneMatch="*"
                )
            except ClientError as exc:
                if _is_precondition_failed(exc):
                    raise JaasError(
                        ErrorCode.DUPLICATE_PUBLISH, f"'{key}' has already been published"
                    ) from exc
                raise

    def write_object(self, key: str, data: bytes) -> None:
        with self._span("storage.write_object"):
            self._client.put_object(Bucket=self.bucket, Key=self._key(key), Body=data)

    def read(self, key: str) -> bytes:
        with self._span("storage.read"):
            response = self._client.get_object(Bucket=self.bucket, Key=self._key(key))
            return response["Body"].read()

    def exists(self, key: str) -> bool:
        with self._span("storage.exists"):
            from botocore.exceptions import ClientError

            try:
                self._client.head_object(Bucket=self.bucket, Key=self._key(key))
                return True
            except ClientError as exc:
                if _is_not_found(exc):
                    return False
                raise

    def list_prefix(self, prefix: str) -> list[str]:
        with self._span("storage.list_prefix"):
            full_prefix = self._key(prefix)
            strip_len = len(self.prefix) + 1 if self.prefix else 0
            paginator = self._client.get_paginator("list_objects_v2")
            keys: list[str] = []
            for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"][strip_len:])
            return sorted(keys)
