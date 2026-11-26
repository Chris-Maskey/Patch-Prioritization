"""Reference method from prior work: the knapsack as a binary integer program.

Goohs et al. (WEIS 2022) and VULCON solve patch selection with integer
programming. We use the HiGHS solver through scipy.optimize.milp, with a zero
relative gap so that "optimal" means proven optimal. scipy is imported here,
not at module load, so the other methods' workers do not load it; the runner
imports it before the timer starts when this method runs.
"""

from __future__ import annotations

from typing import Sequence

from patchsel.model import Task
from patchsel.solvers.base import Solution


def milp_solver(items: Sequence[Task], budget: int, time_limit: float | None = None) -> Solution:
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp

    if not items:
        return Solution([], "optimal")
    values = np.array([t.value for t in items], dtype=float)
    costs = np.array([t.cost for t in items], dtype=float)
    options = {"mip_rel_gap": 0.0}
    if time_limit is not None:
        options["time_limit"] = max(time_limit, 1e-3)
    result = milp(-values, constraints=LinearConstraint(costs[np.newaxis, :], -np.inf, budget),
                  integrality=np.ones(len(items)), bounds=Bounds(0, 1), options=options)
    stats = {"highs_status": int(result.status), "mip_nodes": getattr(result, "mip_node_count", None)}
    if result.x is None:  # stopped before finding any solution: the empty set is the best found
        return Solution([], "unproven", {**stats, "no_solution": True}, status="timeout")
    chosen = [i for i, x in enumerate(result.x) if x > 0.5]
    if result.status == 0:
        return Solution(chosen, "optimal", stats)
    return Solution(chosen, "unproven", stats, status="timeout")
