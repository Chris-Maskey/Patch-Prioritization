"""Shared selection pipeline: reserve mandatory work, preprocess, solve, account."""

from __future__ import annotations

from time import perf_counter_ns

from patchsel.model import Instance, Result
from patchsel.solvers import METHODS, Solver


def select(instance: Instance, method: str, solver: Solver | None = None, **options) -> Result:
    """Run one method on one instance.

    The timed region covers mandatory reservation, preprocessing, the solver,
    and selection recovery. Loading the instance is excluded. ``options`` go to
    the solver, for example ``time_limit`` for branch and bound.
    """
    solver = solver or METHODS[method]
    tasks, budget = instance.tasks, instance.total_budget
    start = perf_counter_ns()

    mandatory = [t for t in tasks if t.mandatory]
    mandatory_cost = sum(t.cost for t in mandatory)
    common = dict(
        instance_id=instance.instance_id, method=method, total_budget=budget,
        mandatory_cost=mandatory_cost, n_tasks=len(tasks), n_mandatory=len(mandatory),
        n_optional=len(tasks) - len(mandatory),
    )
    if mandatory_cost > budget:
        return Result(
            **common, status="infeasible", feasible=False, proof="none",
            shortfall=mandatory_cost - budget, optional_budget=0, n_solver=0, value_sum=0,
            selected_ids=[], deferred_ids=sorted(t.task_id for t in tasks),
            optional_score=0, optional_cost=0, total_cost=0, mandatory_included=False,
            runtime_ns=perf_counter_ns() - start,
        )

    optional_budget = budget - mandatory_cost
    items, deferred = [], []
    for task in tasks:
        if task.mandatory:
            continue
        if task.value == 0 or task.cost > optional_budget:
            deferred.append(task.task_id)
        else:
            items.append(task)
    items.sort(key=lambda t: t.task_id)

    solution = solver(items, optional_budget, **options)
    chosen = set(solution.chosen)
    if len(chosen) != len(solution.chosen):
        raise RuntimeError(f"{method} selected an item more than once")
    selected = [t.task_id for t in mandatory]
    optional_score = optional_cost = 0
    for index, item in enumerate(items):
        if index in chosen:
            selected.append(item.task_id)
            optional_score += item.value
            optional_cost += item.cost
        else:
            deferred.append(item.task_id)
    runtime = perf_counter_ns() - start

    return Result(
        **common, status=solution.status, feasible=True, proof=solution.proof, shortfall=0,
        optional_budget=optional_budget, n_solver=len(items),
        value_sum=sum(t.value for t in items),
        selected_ids=sorted(selected), deferred_ids=sorted(deferred),
        optional_score=optional_score, optional_cost=optional_cost,
        total_cost=mandatory_cost + optional_cost, mandatory_included=True,
        runtime_ns=runtime, stats=solution.stats,
    )
