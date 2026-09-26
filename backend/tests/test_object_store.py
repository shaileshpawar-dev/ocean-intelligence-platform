"""Evidence objects: stored durably, referenced honestly, never invented.

The database holds what a scene is; the object store holds the bytes. What
matters when the store misbehaves is that the platform keeps telling the
truth: a reference exists only if an object was written, a missing object
reads as missing rather than as an error page, and a denial is a warning in a
log rather than a broken water-body page.

The S3 backend is exercised against a stub. **It has never run against a real
bucket** -- no AWS resource for this project exists -- so these tests pin the
contract and the failure handling, not the integration.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.core.objects import (
    LocalObjectStore,
    ObjectRef,
    S3ObjectStore,
    evidence_key,
    get_object_store,
    reset_object_store,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"pretend pixels"


@pytest.fixture
def local_store(tmp_path: Path) -> LocalObjectStore:
    return LocalObjectStore(tmp_path / "objects")


class TestLocalStore:
    def test_put_returns_a_reference_that_describes_the_object(self, local_store):
        ref = local_store.put("evidence/a/b/truecolour.png", PNG, content_type="image/png")
        assert ref is not None
        assert ref.backend == "local"
        assert ref.key == "evidence/a/b/truecolour.png"
        assert ref.size_bytes == len(PNG)
        assert ref.content_type == "image/png"
        assert ref.uri.startswith("file://")

    def test_what_was_written_can_be_read_back(self, local_store):
        local_store.put("k/one.png", PNG)
        handle = local_store.open("k/one.png")
        assert handle is not None
        with handle:
            assert handle.read() == PNG

    def test_a_missing_object_reads_as_missing_not_as_an_error(self, local_store):
        assert local_store.open("nothing/here.png") is None
        assert local_store.exists("nothing/here.png") is False

    def test_a_key_cannot_escape_the_store(self, local_store):
        """Keys are generated internally; a traversal should still not work."""
        assert local_store.put("../../etc/passwd", b"nope") is None
        assert local_store.exists("../../etc/passwd") is False

    def test_the_reference_serialises_with_everything_needed_to_find_it(self):
        ref = ObjectRef("s3", "bucket-x", "evidence/y.png", 12, "image/png")
        payload = ref.to_dict()
        assert payload["uri"] == "s3://bucket-x/evidence/y.png"
        assert payload["backend"] == "s3"
        assert payload["bucket"] == "bucket-x"
        assert payload["key"] == "evidence/y.png"


class _StubS3:
    """Enough of the boto3 S3 client to exercise the three calls used."""

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.fail = fail

    def put_object(self, Bucket: str, Key: str, Body: bytes, **kwargs: object) -> dict:  # noqa: N803
        if self.fail:
            raise self.fail
        self.objects[(Bucket, Key)] = Body
        return {}

    def get_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
        if self.fail:
            raise self.fail
        if (Bucket, Key) not in self.objects:
            raise KeyError("NoSuchKey")
        return {"Body": self.objects[(Bucket, Key)]}

    def head_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
        if self.fail:
            raise self.fail
        if (Bucket, Key) not in self.objects:
            raise KeyError("NoSuchKey")
        return {}


class TestS3Store:
    """Contract and failure handling. Not an integration test."""

    def test_put_and_read_back(self):
        client = _StubS3()
        store = S3ObjectStore("bucket-x", client=client)
        ref = store.put("evidence/x.png", PNG, content_type="image/png")
        assert ref is not None
        assert ref.uri == "s3://bucket-x/evidence/x.png"
        assert store.exists("evidence/x.png") is True
        assert store.open("evidence/x.png") == PNG

    def test_a_denied_upload_returns_none_rather_than_raising(self):
        """An IAM mistake must not become a 500 on a water-body page."""
        store = S3ObjectStore("bucket-x", client=_StubS3(fail=PermissionError("AccessDenied")))
        assert store.put("evidence/x.png", PNG) is None

    def test_a_missing_bucket_returns_none(self):
        store = S3ObjectStore("gone", client=_StubS3(fail=RuntimeError("NoSuchBucket")))
        assert store.put("k.png", PNG) is None
        assert store.open("k.png") is None
        assert store.exists("k.png") is False

    def test_a_missing_object_reads_as_missing(self):
        store = S3ObjectStore("bucket-x", client=_StubS3())
        assert store.open("never/written.png") is None
        assert store.exists("never/written.png") is False

    def test_no_boto3_and_no_credentials_is_reported_once_not_raised(self, monkeypatch):
        store = S3ObjectStore("bucket-x")

        import builtins

        real_import = builtins.__import__

        def no_boto3(name: str, *args: object, **kwargs: object):
            if name == "boto3":
                raise ImportError("No module named 'boto3'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_boto3)
        assert store.put("k.png", PNG) is None
        assert store.exists("k.png") is False


class TestConfiguration:
    def test_the_default_is_a_local_directory_so_a_checkout_needs_no_cloud(self):
        reset_object_store()
        store = get_object_store()
        assert store.backend == "local"
        reset_object_store()

    def test_naming_a_bucket_selects_s3(self, monkeypatch):
        from app.core import objects as objects_module

        reset_object_store()
        monkeypatch.setattr(
            objects_module.settings, "water_evidence_bucket", "oceanai-evidence"
        )
        store = get_object_store()
        assert store.backend == "s3"
        assert store.bucket == "oceanai-evidence"
        reset_object_store()

    def test_keys_say_which_water_body_and_scene_they_belong_to(self):
        key = evidence_key("hussain-sagar-lake", "S2B_MSIL2A_20260616T050649")
        assert key == (
            "evidence/hussain-sagar-lake/S2B_MSIL2A_20260616T050649/truecolour.png"
        )

    def test_an_awkward_scene_id_still_makes_a_safe_key(self):
        key = evidence_key("lake", "a/b c:d")
        assert "/" not in key.split("/", 2)[2].split("/")[0]
        assert " " not in key
