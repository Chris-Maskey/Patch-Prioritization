"""Exact dynamic programs with selection recovery.

Both keep one row of best values plus one "take" bit row per item (a bytearray),
so the full decision table needed for recovery uses O(nB) or O(nP) bytes.
"""

from __future__ import annotations

from typing import Sequence

from patchsel.model import Task
from patchsel.solvers.base import Solution


def dp_budget(items: Sequence[Task], budget: int) -> Solution:
    """best[b] = highest score with cost <= b, over the items seen so far."""
    best = [0] * (budget + 1)
    take = []
    for item in items:
        v, c = item.value, item.cost
        row = bytearray(budget + 1)
        for b in range(budget, c - 1, -1):
            candidate = best[b - c] + v
            if candidate > best[b]:
                best[b] = candidate
                row[b] = 1
        take.append(row)

    chosen, b = [], budget
    for i in range(len(items) - 1, -1, -1):
        if take[i][b]:
            chosen.append(i)
            b -= items[i].cost
    return Solution(chosen[::-1], "optimal", {
        "table_cells": len(items) * (budget + 1),
        "updates": sum(budget - item.cost + 1 for item in items),
    })


def dp_value(items: Sequence[Task], budget: int) -> Solution:
    """cost[p] = lowest cost that reaches score exactly p, over the items seen so far."""
    total = sum(item.value for item in items)
    unreachable = sum(item.cost for item in items) + 1
    cost = [0] + [unreachable] * total
    take = []
    reach = 0  # highest score reachable so far; scores above it stay unreachable
    for item in items:
        v, c = item.value, item.cost
        reach += v
        row = bytearray(reach + 1)
        for p in range(reach, v - 1, -1):
            candidate = cost[p - v] + c
            if candidate < cost[p]:
                cost[p] = candidate
                row[p] = 1
        take.append(row)

    score = max(p for p in range(total + 1) if cost[p] <= budget)
    chosen, p = [], score
    for i in range(len(items) - 1, -1, -1):
        if take[i][p] if p < len(take[i]) else 0:
            chosen.append(i)
            p -= items[i].value
    return Solution(chosen[::-1], "optimal", {
        "table_cells": len(items) * (total + 1),
        "updates": sum(len(row) - item.value for row, item in zip(take, items)),
    })
