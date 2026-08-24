import pytest

from rune_registry.artifact.packaging import build_normalized_archive
from rune_registry.common.errors import ErrorCode, RuneError
from rune_registry.drafts.store import DraftStore


def test_create_blank_draft_seeds_a_starter_manifest(tmp_path):
    """A blank draft is never truly empty — it's seeded with a placeholder
    manifest.yaml, the one document with no sensible default (see
    artifact/packaging.py's REQUIRED_PACKAGE_FILES), so the first Validate/
    Publish doesn't immediately fail with MISSING_REQUIRED_FILE. The other
    three documents are optional everywhere now, so there's nothing to seed
    for them."""
    store = DraftStore(tmp_path)

    draft = store.create(owner_user="usr_1", owner_tenant="tnt_1")

    assert draft.id.startswith("draft_")
    assert draft.forked_from_id is None
    assert store.get(draft.id) == draft
    assert store.list_files(draft.id) == ["manifest.yaml"]


def test_write_read_and_list_files(tmp_path):
    store = DraftStore(tmp_path)
    draft = store.create(owner_user="usr_1", owner_tenant="tnt_1")

    store.write_file(draft.id, "manifest.yaml", b"id: acme.text.foo\n")
    store.write_file(draft.id, "schema.json", b"{}")

    assert store.read_file(draft.id, "manifest.yaml") == b"id: acme.text.foo\n"
    assert store.list_files(draft.id) == ["manifest.yaml", "schema.json"]


def test_write_file_supports_nested_paths(tmp_path):
    store = DraftStore(tmp_path)
    draft = store.create(owner_user="usr_1", owner_tenant="tnt_1")

    store.write_file(draft.id, "tests/test_basic.py", b"def test_x(): pass\n")

    assert store.list_files(draft.id) == ["manifest.yaml", "tests/test_basic.py"]
    assert store.read_file(draft.id, "tests/test_basic.py") == b"def test_x(): pass\n"


def test_delete_file_removes_it(tmp_path):
    store = DraftStore(tmp_path)
    draft = store.create(owner_user="usr_1", owner_tenant="tnt_1")
    store.write_file(draft.id, "manifest.yaml", b"content")

    store.delete_file(draft.id, "manifest.yaml")

    assert store.read_file(draft.id, "manifest.yaml") is None
    assert store.list_files(draft.id) == []


def test_read_unknown_file_returns_none(tmp_path):
    store = DraftStore(tmp_path)
    draft = store.create(owner_user="usr_1", owner_tenant="tnt_1")
    assert store.read_file(draft.id, "does-not-exist.yaml") is None


def test_get_unknown_draft_returns_none(tmp_path):
    store = DraftStore(tmp_path)
    assert store.get("draft_ghost") is None


def test_delete_removes_the_whole_draft(tmp_path):
    store = DraftStore(tmp_path)
    draft = store.create(owner_user="usr_1", owner_tenant="tnt_1")
    store.write_file(draft.id, "manifest.yaml", b"content")

    store.delete(draft.id)

    assert store.get(draft.id) is None


def test_fork_populates_files_from_a_published_archive(tmp_path):
    store = DraftStore(tmp_path)
    archive = build_normalized_archive(
        {
            "manifest.yaml": b"id: acme.text.foo\n",
            "schema.json": b"{}",
            "permissions.yaml": b"[]",
            "dependencies.yaml": b"[]",
        }
    )

    draft = store.create(
        owner_user="usr_1",
        owner_tenant="tnt_1",
        fork_archive_bytes=archive,
        forked_from_id="acme.text.foo",
        forked_from_version="1.0.0",
    )

    assert draft.forked_from_id == "acme.text.foo"
    assert draft.forked_from_version == "1.0.0"
    assert set(store.list_files(draft.id)) == {
        "manifest.yaml",
        "schema.json",
        "permissions.yaml",
        "dependencies.yaml",
    }
    assert store.read_file(draft.id, "manifest.yaml") == b"id: acme.text.foo\n"


class TestPathSafety:
    """The draft file path comes straight from a request body/path param —
    this is a real trust boundary, not defensive theater."""

    @pytest.mark.parametrize(
        "bad_path",
        [
            "../../../etc/passwd",
            "/etc/passwd",
            "a/../../b",
            "",
            "_meta.json",
        ],
    )
    def test_write_rejects_path_traversal(self, tmp_path, bad_path):
        store = DraftStore(tmp_path)
        draft = store.create(owner_user="usr_1", owner_tenant="tnt_1")

        with pytest.raises(RuneError) as excinfo:
            store.write_file(draft.id, bad_path, b"malicious")
        assert excinfo.value.code == ErrorCode.INVALID_FILE_PATH

    def test_traversal_attempt_does_not_escape_the_draft_directory(self, tmp_path):
        store = DraftStore(tmp_path)
        draft = store.create(owner_user="usr_1", owner_tenant="tnt_1")
        sentinel = tmp_path / "outside.txt"

        with pytest.raises(RuneError):
            store.write_file(draft.id, "../../outside.txt", b"pwned")

        assert not sentinel.exists()

    def test_read_rejects_path_traversal(self, tmp_path):
        store = DraftStore(tmp_path)
        draft = store.create(owner_user="usr_1", owner_tenant="tnt_1")
        with pytest.raises(RuneError):
            store.read_file(draft.id, "../../../etc/passwd")

    def test_delete_rejects_path_traversal(self, tmp_path):
        store = DraftStore(tmp_path)
        draft = store.create(owner_user="usr_1", owner_tenant="tnt_1")
        with pytest.raises(RuneError):
            store.delete_file(draft.id, "../../../etc/passwd")
