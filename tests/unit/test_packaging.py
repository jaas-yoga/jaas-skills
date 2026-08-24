import pytest

from rune_registry.artifact.packaging import (
    DEFAULT_PACKAGE_FILE_CONTENTS,
    build_normalized_archive,
    collect_package_files,
    compute_digest,
)
from tests.fixtures.package_dir import write_package_dir

SAMPLE_FILES = {
    "manifest.yaml": b"1",
    "schema.json": b"2",
    "permissions.yaml": b"3",
    "dependencies.yaml": b"4",
}


def test_collect_package_files_reads_all_four(tmp_path):
    write_package_dir(tmp_path)
    files = collect_package_files(tmp_path)
    assert set(files) == set(SAMPLE_FILES)


def test_archive_is_deterministic_regardless_of_dict_order():
    reordered = dict(reversed(SAMPLE_FILES.items()))
    assert build_normalized_archive(SAMPLE_FILES) == build_normalized_archive(reordered)


def test_digest_changes_when_content_changes():
    tampered = dict(SAMPLE_FILES, **{"manifest.yaml": b"1-tampered"})
    original_digest = compute_digest(build_normalized_archive(SAMPLE_FILES))
    tampered_digest = compute_digest(build_normalized_archive(tampered))
    assert original_digest != tampered_digest


def test_digest_has_sha256_prefix():
    archive = build_normalized_archive({"manifest.yaml": b"x"})
    digest = compute_digest(archive)
    assert digest.startswith("sha256:")
    assert len(digest.split(":")[1]) == 64


def test_collect_package_files_missing_manifest_raises(tmp_path):
    """manifest.yaml is the only file with no sensible default — id/name/
    version/owner are the skill's own identity."""
    write_package_dir(tmp_path)
    (tmp_path / "manifest.yaml").unlink()
    with pytest.raises(FileNotFoundError):
        collect_package_files(tmp_path)


@pytest.mark.parametrize(
    "optional_file", ["schema.json", "permissions.yaml", "dependencies.yaml"]
)
def test_collect_package_files_defaults_the_optional_documents(tmp_path, optional_file):
    write_package_dir(tmp_path)
    (tmp_path / optional_file).unlink()

    files = collect_package_files(tmp_path)

    assert set(files) == set(SAMPLE_FILES)
    assert files[optional_file] == DEFAULT_PACKAGE_FILE_CONTENTS[optional_file]
