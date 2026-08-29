"""Artefact storage: original uploads, templates, signature images, final PDFs.

Two backends, chosen by STORAGE_BACKEND:

* ``s3`` -- MinIO or Amazon S3, for deployments with room to run it.
* ``local`` -- a plain directory on a mounted volume. MinIO idles at a few
  hundred megabytes, which is a quarter of a 1 GB machine; on small hosts the
  filesystem is the better object store.

Both expose the same interface, so nothing above this module knows which is in
use. Files are always served *through* the API, never by a direct link to the
storage layer: these documents contain SSNs, so every read passes the same
authorisation check.
"""
from __future__ import annotations

import io
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings
from app.core.exceptions import StorageError

logger = logging.getLogger(__name__)

PREFIX_TEMPLATES = "templates"
PREFIX_CONTRACTS = "contracts"
PREFIX_SIGNATURES = "signatures"
PREFIX_FINAL = "final"


class S3Storage:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                aws_access_key_id=settings.minio_access_key,
                aws_secret_access_key=settings.minio_secret_key,
                config=Config(signature_version="s3v4"),
                region_name="us-east-1",
            )
        return self._client

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=settings.minio_bucket)
        except ClientError:
            try:
                self.client.create_bucket(Bucket=settings.minio_bucket)
            except (ClientError, BotoCoreError) as exc:
                raise StorageError(f"Could not create bucket: {exc}") from exc

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/pdf") -> str:
        try:
            self.client.put_object(
                Bucket=settings.minio_bucket, Key=key, Body=data, ContentType=content_type
            )
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"Upload failed for {key}: {exc}") from exc
        return key

    def put_file(self, key: str, path: str, content_type: str = "application/pdf") -> str:
        with open(path, "rb") as handle:
            return self.put_bytes(key, handle.read(), content_type)

    def get_bytes(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=settings.minio_bucket, Key=key)
            return response["Body"].read()
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"Download failed for {key}: {exc}") from exc

    def stream(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.get_bytes(key))

    def presigned_url(self, key: str, filename: str | None = None, ttl: int | None = None) -> str:
        params = {"Bucket": settings.minio_bucket, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=ttl or settings.presigned_url_ttl_seconds,
            )
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"Could not sign URL for {key}: {exc}") from exc

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=settings.minio_bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to delete %s: %s", key, exc)

    @contextmanager
    def local_copy(self, key: str, suffix: str = ".pdf"):
        """Materialise an object on local disk; pdfplumber and pypdf want a path."""
        handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            handle.write(self.get_bytes(key))
            handle.flush()
            handle.close()
            yield handle.name
        finally:
            try:
                os.unlink(handle.name)
            except OSError:
                pass


class LocalStorage:
    """Filesystem-backed store with the same interface as S3Storage.

    Keys are treated as relative paths under `storage_dir`; each is checked to
    stay inside that root, so a crafted key cannot escape via `..`.
    """

    def __init__(self, root: str | None = None):
        self.root = Path(root or settings.storage_dir)

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        root = self.root.resolve()
        if not str(candidate).startswith(str(root)):
            raise StorageError(f"Refusing to access a key outside the storage root: {key}")
        return candidate

    def ensure_bucket(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(f"Could not create the storage directory: {exc}") from exc

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/pdf") -> str:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write then rename: a crash mid-write must not leave a truncated
            # contract behind a valid-looking key.
            temporary = path.with_suffix(path.suffix + ".partial")
            temporary.write_bytes(data)
            temporary.replace(path)
        except OSError as exc:
            raise StorageError(f"Upload failed for {key}: {exc}") from exc
        return key

    def put_file(self, key: str, path: str, content_type: str = "application/pdf") -> str:
        with open(path, "rb") as handle:
            return self.put_bytes(key, handle.read(), content_type)

    def get_bytes(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except OSError as exc:
            raise StorageError(f"Download failed for {key}: {exc}") from exc

    def stream(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.get_bytes(key))

    def presigned_url(self, key: str, filename: str | None = None, ttl: int | None = None) -> str:
        raise StorageError(
            "The local backend has no presigned URLs; files are served through the API."
        )

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to delete %s: %s", key, exc)

    @contextmanager
    def local_copy(self, key: str, suffix: str = ".pdf"):
        # Already on disk; pdfplumber can open it in place.
        yield str(self._path(key))


def _build_storage():
    if settings.storage_backend == "local":
        return LocalStorage()
    return S3Storage()


storage = _build_storage()


def template_key(template_id, filename: str = "source.pdf") -> str:
    return f"{PREFIX_TEMPLATES}/{template_id}/{filename}"


def contract_key(contract_id, filename: str = "original.pdf") -> str:
    return f"{PREFIX_CONTRACTS}/{contract_id}/{filename}"


def signature_key(contract_id, signature_id) -> str:
    return f"{PREFIX_SIGNATURES}/{contract_id}/{signature_id}.png"


def final_key(contract_id) -> str:
    return f"{PREFIX_FINAL}/{contract_id}/signed.pdf"
