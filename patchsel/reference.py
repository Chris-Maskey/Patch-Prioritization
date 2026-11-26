"""Exhaustive search, used only as an independent reference in tests."""

from __future__ import annotations

from typing import Sequence

from patchsel.model import Task

MAX_ITEMS = 18


def exhaustive(items: Sequence[Task], budget: int) -> tuple[int, list[int]]:
    """Return (best score, one optimal index list) by checking every subset."""
    if len(items) > MAX_ITEMS:
        raise ValueError(f"exhaustive search is limited to {MAX_ITEMS} items")
    best_score, best_mask = 0, 0
    for mask in range(1 << len(items)):
        cost = score = 0
        for i, item in enumerate(items):
            if mask >> i & 1:
                cost += item.cost
                score += item.value
        if cost <= budget and score > best_score:
            best_score, best_mask = score, mask
    return best_score, [i for i in range(len(items)) if best_mask >> i & 1]
