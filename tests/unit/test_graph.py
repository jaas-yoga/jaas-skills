import pytest

from rune_registry.common.errors import ErrorCode, RuneError
from rune_registry.validation.graph import find_cycles, validate_no_cycles


def test_acyclic_graph_has_no_cycles():
    graph = {"a": ["b"], "b": ["c"], "c": []}
    assert find_cycles(graph) == []
    validate_no_cycles(graph)  # should not raise


def test_direct_cycle_detected():
    graph = {"a": ["b"], "b": ["a"]}
    cycles = find_cycles(graph)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"a", "b"}


def test_self_loop_detected():
    graph = {"a": ["a"]}
    cycles = find_cycles(graph)
    assert cycles == [["a"]]


def test_indirect_cycle_detected():
    graph = {"a": ["b"], "b": ["c"], "c": ["a"]}
    cycles = find_cycles(graph)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"a", "b", "c"}


def test_validate_no_cycles_raises_with_stable_code():
    graph = {"a": ["b"], "b": ["a"]}
    with pytest.raises(RuneError) as exc_info:
        validate_no_cycles(graph)
    assert exc_info.value.code == ErrorCode.CIRCULAR_DEPENDENCY
    assert "cycles" in exc_info.value.details


def test_diamond_shaped_graph_is_not_a_false_positive():
    # a depends on b and c; both depend on d. Not a cycle even though d is
    # reachable via two paths.
    graph = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
    assert find_cycles(graph) == []
