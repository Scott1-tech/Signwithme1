"""The filesystem backend used on small hosts, where MinIO does not fit."""
import pytest

from app.core.exceptions import StorageError
from app.services.storage import LocalStorage


@pytest.fixture
def store(tmp_path) -> LocalStorage:
    backend = LocalStorage(root=str(tmp_path / "storage"))
    backend.ensure_bucket()
    return backend


def test_round_trip(store):
    store.put_bytes("contracts/abc/original.pdf", b"%PDF-1.4 hello")
    assert store.get_bytes("contracts/abc/original.pdf") == b"%PDF-1.4 hello"
    assert store.stream("contracts/abc/original.pdf").read() == b"%PDF-1.4 hello"


def test_nested_keys_create_their_directories(store):
    store.put_bytes("final/deep/nested/signed.pdf", b"x")
    assert store.get_bytes("final/deep/nested/signed.pdf") == b"x"


def test_local_copy_hands_back_a_real_path(store):
    store.put_bytes("templates/t/source.pdf", b"%PDF-1.4")
    with store.local_copy("templates/t/source.pdf") as path:
        with open(path, "rb") as handle:
            assert handle.read() == b"%PDF-1.4"


def test_a_traversing_key_is_refused(store):
    """A key is attacker-influenced only indirectly, but writing outside the
    storage root should never be reachable at all."""
    with pytest.raises(StorageError):
        store.put_bytes("../../etc/passwd", b"nope")
    with pytest.raises(StorageError):
        store.get_bytes("contracts/../../../etc/hosts")


def test_delete_is_idempotent(store):
    store.put_bytes("a/b.pdf", b"x")
    store.delete("a/b.pdf")
    store.delete("a/b.pdf")
    with pytest.raises(StorageError):
        store.get_bytes("a/b.pdf")


def test_a_partial_write_leaves_no_readable_key(store, monkeypatch):
    """Write-then-rename: a crash mid-write must not leave a truncated contract
    behind a key that looks valid."""
    original = LocalStorage.put_bytes

    def explode(self, key, data, content_type="application/pdf"):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(path.suffix + ".partial").write_bytes(data[:3])
        raise OSError("disk full")

    monkeypatch.setattr(LocalStorage, "put_bytes", explode)
    with pytest.raises(OSError):
        store.put_bytes("c/d.pdf", b"%PDF-1.4 complete")
    monkeypatch.setattr(LocalStorage, "put_bytes", original)
    with pytest.raises(StorageError):
        store.get_bytes("c/d.pdf")
