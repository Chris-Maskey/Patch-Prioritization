"""Greedy baselines with skip-and-continue and stable task-ID tie-breaking."""

from __future__ import annotations

from functools import cmp_to_key
from typing import Sequence

from patchsel.model import Task
from patchsel.solvers.base import Solution


def _fill(items: Sequence[Task], order: list[int], budget: int) -> Solution:
    chosen, remaining, skipped = [], budget, 0
    for index in order:
        if items[index].cost <= remaining:
            chosen.append(index)
            remaining -= items[index].cost
        else:
            skipped += 1
    return Solution(chosen, "heuristic", {"skipped": skipped})


def severity_first(items: Sequence[Task], budget: int) -> Solution:
    """Highest CVSS value first; ties by task ID."""
    order = sorted(range(len(items)), key=lambda i: (-items[i].value, items[i].task_id))
    return _fill(items, order, budget)


def ratio_order(items: Sequence[Task]) -> list[int]:
    """Indices by decreasing value/cost, compared exactly; ties by task ID."""

    def compare(i: int, j: int) -> int:
        left = items[i].value * items[j].cost
        right = items[j].value * items[i].cost
        if left != right:
            return -1 if left > right else 1
        return -1 if items[i].task_id < items[j].task_id else 1

    return sorted(range(len(items)), key=cmp_to_key(compare))


def ratio_greedy(items: Sequence[Task], budget: int) -> Solution:
    """Highest value/cost first, compared exactly with integer cross-multiplication."""
    return _fill(items, ratio_order(items), budget)
