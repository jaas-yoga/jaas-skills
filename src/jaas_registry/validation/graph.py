"""Dependency graph construction and cycle detection.

Design ref: design.md §4.4.3 ("rejected by strongly connected component detection"),
implementation-plan.md Phase 1 task 3.
"""

from __future__ import annotations

from jaas_registry.common.errors import ErrorCode, JaasError


def find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's SCC algorithm, returning components that constitute a cycle.

    `graph` maps a skill id to the ids it directly depends on. A component is a
    cycle if it has more than one node, or is a single node with a self-loop.
    Dependency ids not present as keys are treated as external leaves.
    """
    index_counter = 0
    stack: list[str] = []
    on_stack: dict[str, bool] = {}
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    cycles: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index_counter
        index[node] = index_counter
        lowlink[node] = index_counter
        index_counter += 1
        stack.append(node)
        on_stack[node] = True

        for successor in graph.get(node, []):
            if successor not in index:
                strongconnect(successor)
                lowlink[node] = min(lowlink[node], lowlink[successor])
            elif on_stack.get(successor):
                lowlink[node] = min(lowlink[node], index[successor])

        if lowlink[node] == index[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack[member] = False
                component.append(member)
                if member == node:
                    break
            if len(component) > 1 or node in graph.get(node, []):
                cycles.append(component)

    for node in graph:
        if node not in index:
            strongconnect(node)

    return cycles


def validate_no_cycles(graph: dict[str, list[str]]) -> None:
    cycles = find_cycles(graph)
    if cycles:
        raise JaasError(
            ErrorCode.CIRCULAR_DEPENDENCY,
            "dependency graph contains a cycle",
            details={"cycles": cycles},
        )
