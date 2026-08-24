"""Security test suite: malformed manifest fuzzing.

implementation-plan.md Phase 7 task 4. The property under test throughout is
robustness, not any particular acceptance/rejection outcome: validation must
always resolve to a `JaasError` with a stable code, never an unhandled
exception (which could crash a worker or leak internals), and never hang
(regex/parsing denial-of-service).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from jaas_registry.common.errors import JaasError
from jaas_registry.validation.rules import (
    validate_dependencies,
    validate_io_schema,
    validate_manifest,
    validate_permissions,
)

# Arbitrary JSON-shaped garbage: the kind of payload a hostile or buggy client
# might submit as a "manifest.yaml" body once parsed to Python objects.
json_scalar = st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text()
json_value = st.recursive(
    json_scalar,
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(), children, max_size=5)
    ),
    max_leaves=20,
)

_SUITE_SETTINGS = settings(
    max_examples=200,
    deadline=timedelta(milliseconds=500),
    suppress_health_check=[HealthCheck.too_slow],
)


@_SUITE_SETTINGS
@given(data=json_value)
def test_validate_manifest_never_raises_unhandled_exception(data):
    try:
        validate_manifest(data)
    except JaasError:
        pass  # the only acceptable rejection


@_SUITE_SETTINGS
@given(data=json_value)
def test_validate_dependencies_never_raises_unhandled_exception(data):
    try:
        validate_dependencies(data)
    except JaasError:
        pass


@_SUITE_SETTINGS
@given(data=json_value)
def test_validate_permissions_never_raises_unhandled_exception(data):
    try:
        validate_permissions(data)
    except JaasError:
        pass


@_SUITE_SETTINGS
@given(data=json_value)
def test_validate_io_schema_never_raises_unhandled_exception(data):
    try:
        validate_io_schema(data)
    except JaasError:
        pass


VALID_MANIFEST_SHAPE = {
    "apiVersion": "v1",
    "name": "Summarizer",
    "description": "desc",
    "owner": {"team": "platform"},
    "entrypoint": "executor.py",
    "category": "nlp",
    "runtime": [{"family": "python", "versionRange": ">=1.0.0"}],
}


@settings(max_examples=200, deadline=timedelta(milliseconds=200))
@given(candidate_id=st.text(max_size=2000))
def test_id_regex_never_hangs_on_adversarial_input(candidate_id):
    """Regex-shaped id validation must not be vulnerable to catastrophic
    backtracking (ReDoS) regardless of what a caller submits as `id`."""
    manifest = dict(VALID_MANIFEST_SHAPE, id=candidate_id, version="1.0.0")
    try:
        validate_manifest(manifest)
    except JaasError:
        pass


@settings(max_examples=50, deadline=timedelta(milliseconds=200))
@given(n=st.integers(min_value=1, max_value=2000))
def test_id_regex_never_hangs_on_pathological_dash_repetition(n):
    """Specifically targets the nested-quantifier shape of ID_PATTERN
    (`(?:-[a-z0-9]+)*` inside a repeated group) with the classic ReDoS input
    family: a long run of the "almost matches" character with no terminator."""
    manifest = dict(VALID_MANIFEST_SHAPE, id="a" + "-" * n, version="1.0.0")
    try:
        validate_manifest(manifest)
    except JaasError:
        pass


@settings(max_examples=200, deadline=timedelta(milliseconds=200))
@given(candidate_version=st.text(max_size=500))
def test_version_parsing_never_hangs_on_adversarial_input(candidate_version):
    manifest = dict(VALID_MANIFEST_SHAPE, id="acme.text.summarizer", version=candidate_version)
    try:
        validate_manifest(manifest)
    except JaasError:
        pass


@pytest.mark.parametrize(
    "hostile_id",
    [
        "\x00\x00\x00",
        "a" * 100_000,
        "../../etc/passwd",
        "'; DROP TABLE skills; --",
        "<script>alert(1)</script>",
        "a.b.c\ninjected-header: value",
        "🎉.🎉.🎉",
    ],
)
def test_known_hostile_id_payloads_are_cleanly_rejected(hostile_id):
    manifest = dict(VALID_MANIFEST_SHAPE, id=hostile_id, version="1.0.0")
    with pytest.raises(JaasError):
        validate_manifest(manifest)


def test_non_dict_top_level_input_is_rejected_not_crashed():
    for garbage in (None, [], "just a string", 42, 3.14, True):
        with pytest.raises(JaasError):
            validate_manifest(garbage)
