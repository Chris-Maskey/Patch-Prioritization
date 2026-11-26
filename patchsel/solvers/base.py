"""Common solver interface.

A solver takes ``(items, budget)`` and returns a :class:`Solution`. ``items`` are
the optional tasks left after common preprocessing: every item has
0 < cost <= budget and value > 0, and the list is ordered by task ID. The
solver returns indices into that list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from patchsel.model import Task


@dataclass(slots=True)
class Solution:
    chosen: list[int]
    proof: str  # optimal | heuristic | unproven
    stats: dict = field(default_factory=dict)
    status: str = "completed"  # completed | timeout (selection is the best found so far)


Solver = Callable[..., Solution]  # (items, budget, **options) -> Solution
