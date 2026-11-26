"""Registry of the selection methods compared in the study."""

from patchsel.solvers.base import Solution, Solver
from patchsel.solvers.bnb import branch_and_bound
from patchsel.solvers.dp import dp_budget, dp_value
from patchsel.solvers.greedy import ratio_greedy, severity_first
from patchsel.solvers.milp import milp_solver

METHODS: dict[str, Solver] = {
    "severity": severity_first,
    "ratio": ratio_greedy,
    "dp_budget": dp_budget,
    "dp_value": dp_value,
    "bnb": branch_and_bound,
    "milp": milp_solver,  # reference from prior work (integer programming, HiGHS)
}

__all__ = ["METHODS", "Solution", "Solver"]
