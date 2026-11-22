"""Where large evidence objects live.

The database holds what a scene *is* -- its id, sensor, acquisition date,
footprint, cover fractions, the derived index and its provenance -- and an
object store holds the bytes. Putting a satellite image in PostgreSQL would
make every backup and every restore carry pixels that a file store handles
better, and the row is the evidence either way.

Two backends behind one interface:

``LocalObjectStore``
    A directory. This is development and the default, so a checkout needs no
    cloud account and the tests need no network.

``S3ObjectStore``
    Used when ``WATER_EVIDENCE_BUCKET`` is set. **Never exercised against a
    real bucket**: no AWS resource for this project exists. The code and its
    configuration are validated locally against a stub, and that limitation is
    recorded here rather than implied away.

Everything an object store does can fail -- a bucket that is not there, a
credential that is not allowed, a network that is down -- and none of it is
worth an error page. A failed read returns ``None`` and a failed write returns
``None``; callers show the metadata they already have. What must never happen
is a *silent invention*: a reference is stored only after the object is
actually written, so a key in the database always meant something once.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ObjectRef:
    """A durable reference to one stored object.

    ``backend`` and ``bucket`` travel with the key so a reference stored by
    one deployment can be recognised, or rejected, by another.
    """

    backend: str
    bucket: str
    key: str
    size_bytes: int | None = None
    content_type: str | None = None

    @property
    def uri(self) -> str:
        """A single string that identifies the object."""
        if self.backend == "s3":
            return f"s3://{self.bucket}/{self.key}"
        return f"file://{self.bucket}/{self.key}"

    def to_dict(self) -> dict:
        """Serialise for storage alongside the evidence metadata."""
        return {
            "backend": self.backend,
            "bucket": self.bucket,
            "key": self.key,
            "uri": self.uri,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
        }


class ObjectStore(Protocol):
    """The three things the platform asks of an object store."""

    backend: str
    bucket: str

    def put(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> ObjectRef | None:
        """Store bytes. Returns None when the store is unavailable."""

    def open(self, key: str) -> BinaryIO | None:
        """Read an object back, or None when it is missing or unreachable."""

    def exists(self, key: str) -> bool:
        """Whether the object is there. False when the store cannot say."""


class LocalObjectStore:
    """Objects as files under a directory. The development default."""

    backend = "local"

    def __init__(self, root: Path | str) -> None:
        """Create a store rooted at ``root``, making it if it is absent.

        The root is resolved to an absolute path with forward slashes: a
        stored reference has to mean the same thing to a job started from a
        different directory, and a bare relative path in a database column is a
        reference to nowhere in particular.
        """
        self.root = Path(root).expanduser().resolve()
        self.bucket = self.root.as_posix()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # An unwritable path is a configuration problem, not a crash: the
            # store reports itself unavailable and the platform carries on.
            logger.warning(
                "object_store_unwritable",
                extra={"root": str(self.root), "error": str(exc)},
            )

    def _path(self, key: str) -> Path:
        # Keys are generated internally, but a traversal would be a nasty way
        # to find that out, so resolve and confine.
        candidate = (self.root / key).resolve()
        root = self.root.resolve()
        if not str(candidate).startswith(str(root)):
            raise ValueError(f"object key escapes the store root: {key!r}")
        return candidate

    def put(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> ObjectRef | None:
        """Write the bytes to a file, creating parent directories."""
        try:
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except (OSError, ValueError) as exc:
            logger.warning("object_put_failed", extra={"key": key, "error": str(exc)})
            return None
        return ObjectRef(
            backend=self.backend,
            bucket=self.bucket,
            key=key,
            size_bytes=len(data),
            content_type=content_type,
        )

    def open(self, key: str) -> BinaryIO | None:
        """Open the file, or None when it is not there."""
        try:
            return self._path(key).open("rb")
        except (OSError, ValueError):
            return None

    def exists(self, key: str) -> bool:
        """Whether the file exists."""
        try:
            return self._path(key).is_file()
        except ValueError:
            return False

    def clear(self) -> None:
        """Remove everything. Tests only."""
        shutil.rmtree(self.root, ignore_errors=True)


class S3ObjectStore:
    """Objects in an S3 bucket.

    **Unverified against AWS.** No bucket for this project exists, so this
    path has been exercised only against a stubbed client. The calls are the
    ordinary three (``put_object``, ``get_object``, ``head_object``) and the
    task role in ``infra/aws/staging.yaml`` grants exactly those on one
    bucket, but "it should work" is the strongest claim available.
    """

    backend = "s3"

    def __init__(self, bucket: str, *, client: object | None = None) -> None:
        """Create a store for ``bucket``; ``client`` is for tests."""
        self.bucket = bucket
        self._client = client
        self._unavailable_logged = False

    @property
    def client(self) -> object | None:
        """The boto3 client, or None when boto3 or credentials are absent."""
        if self._client is None:
            try:
                import boto3
            except ImportError:
                self._note_unavailable("boto3 is not installed")
                return None
            try:
                self._client = boto3.client("s3")
            except Exception as exc:
                self._note_unavailable(str(exc))
                return None
        return self._client

    def _note_unavailable(self, reason: str) -> None:
        """Log once, not on every object."""
        if not self._unavailable_logged:
            logger.warning(
                "object_store_unavailable",
                extra={
                    "backend": self.backend,
                    "bucket": self.bucket,
                    "reason": reason[:200],
                },
            )
            self._unavailable_logged = True

    def put(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> ObjectRef | None:
        """Upload, returning None on any failure -- including a denial."""
        client = self.client
        if client is None:
            return None
        extra = {"ContentType": content_type} if content_type else {}
        try:
            client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        except Exception as exc:
            logger.warning(
                "object_put_failed",
                extra={"bucket": self.bucket, "key": key, "error": str(exc)[:200]},
            )
            return None
        return ObjectRef(
            backend=self.backend,
            bucket=self.bucket,
            key=key,
            size_bytes=len(data),
            content_type=content_type,
        )

    def open(self, key: str) -> BinaryIO | None:
        """Fetch an object's body, or None when missing or forbidden."""
        client = self.client
        if client is None:
            return None
        try:
            response = client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            logger.info(
                "object_get_failed",
                extra={"bucket": self.bucket, "key": key, "error": str(exc)[:200]},
            )
            return None
        return response.get("Body")

    def exists(self, key: str) -> bool:
        """Whether the object is there; False when the store cannot say."""
        client = self.client
        if client is None:
            return False
        try:
            client.head_object(Bucket=self.bucket, Key=key)
        except Exception:
            return False
        return True


_store: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    """The configured store: S3 when a bucket is named, otherwise a directory."""
    global _store
    if _store is None:
        bucket = (settings.water_evidence_bucket or "").strip()
        if bucket:
            _store = S3ObjectStore(bucket)
            logger.info("object_store", extra={"backend": "s3", "bucket": bucket})
        else:
            root = Path(settings.water_object_dir)
            _store = LocalObjectStore(root)
            logger.info("object_store", extra={"backend": "local", "root": str(root)})
    return _store


def reset_object_store() -> None:
    """Forget the configured store. Tests, and after changing settings."""
    global _store
    _store = None


def evidence_key(water_body_slug: str, scene_id: str, kind: str = "truecolour") -> str:
    """The key an evidence object is stored under.

    Readable on purpose: an operator listing the bucket should be able to see
    which water body and which scene an object belongs to without a lookup.
    """
    safe_scene = "".join(c if c.isalnum() or c in "-_." else "-" for c in scene_id)
    return f"evidence/{water_body_slug}/{safe_scene}/{kind}.png"
