"""S3-compatible object storage (MinIO locally, S3 in prod). Implements the
ObjectStorage interface so routes stay decoupled from boto3 (architecture §7, §10).

Large media is uploaded by the client straight to storage via a presigned PUT URL,
so video files (FR-01) never pass through the application tier.
"""
from __future__ import annotations

from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings


class S3Storage:
    """ObjectStorage backed by boto3 against an S3-compatible endpoint."""

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str):
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            # MinIO needs SigV4 + path-style addressing (no virtual-host buckets).
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def presigned_put_url(self, key: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def presigned_get_url(self, key: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def upload_file(self, local_path: str, key: str, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else None
        self._client.upload_file(local_path, self._bucket, key, ExtraArgs=extra)

    def stat(self, key: str) -> dict | None:
        try:
            head = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        return {"size_bytes": head["ContentLength"]}

    def download_to_path(self, key: str, dest_path: str) -> None:
        self._client.download_file(self._bucket, key, dest_path)


@lru_cache
def get_storage() -> S3Storage:
    """FastAPI dependency: a process-wide storage client built from settings."""
    return S3Storage(
        endpoint=settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        bucket=settings.s3_bucket,
    )
