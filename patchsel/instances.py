"""Seeded backlog generation from the prepared pool."""

from __future__ import annotations

from dataclasses import replace
from math import gcd
import random

from patchsel.model import Instance, Task

COST_MODELS = ("equal", "uniform", "correlated")
REPRESENTATIONS = ("original", "x6", "gcd")  # task 11: time-unit sensitivity
TIME_UNIT_MINUTES = 30
EQUAL_COST = 4
UNIFORM_RANGE = (1, 20)


def task_cost(model: str, value: int, rng: random.Random) -> int:
    if model == "equal":
        return EQUAL_COST
    if model == "uniform":
        return rng.randint(*UNIFORM_RANGE)
    if model == "correlated":
        return max(1, -(-value // 5) + rng.choice((-1, 0, 1)))  # ceil(v/5) + jitter
    raise ValueError(f"unknown cost model {model!r}; choose from {COST_MODELS}")


def instance_id(n_tasks: int, cost_model: str, budget_pct: int, seed: int) -> str:
    return f"N{n_tasks:04d}-{cost_model}-b{budget_pct:02d}-s{seed}"


def generate(pool: list[dict], n_tasks: int, cost_model: str, budget_pct: int, seed: int,
             pool_sha256: str | None = None) -> Instance:
    """Sample ``n_tasks`` pool rows without replacement and attach costs and a budget.

    The sample depends only on (n_tasks, seed), so every cost model and budget
    fraction with the same size and seed shares the same vulnerability groups.
    The optional budget is floor(budget_pct / 100 * total optional cost), and the
    total budget adds the mandatory (KEV) cost.
    """
    if not 1 <= n_tasks <= len(pool):
        raise ValueError(f"n_tasks must be between 1 and {len(pool)}")
    if not 0 <= budget_pct <= 100:
        raise ValueError("budget_pct must be between 0 and 100")
    if cost_model not in COST_MODELS:
        raise ValueError(f"unknown cost model {cost_model!r}; choose from {COST_MODELS}")

    sample_rng = random.Random(f"sample|{n_tasks}|{seed}")
    cost_rng = random.Random(f"cost|{cost_model}|{n_tasks}|{seed}")
    rows = sorted((pool[i] for i in sample_rng.sample(range(len(pool)), n_tasks)),
                  key=lambda row: row["group_id"])
    tasks = [
        Task(task_id=row["group_id"], value=row["value"],
             cost=task_cost(cost_model, row["value"], cost_rng),
             mandatory=row["kev_status"] == "match", kev_status=row["kev_status"])
        for row in rows
    ]
    mandatory_cost = sum(t.cost for t in tasks if t.mandatory)
    optional_total = sum(t.cost for t in tasks if not t.mandatory)
    optional_budget = budget_pct * optional_total // 100
    meta = {
        "seed": seed, "n_tasks": n_tasks, "cost_model": cost_model, "budget_pct": budget_pct,
        "time_unit_minutes": TIME_UNIT_MINUTES, "sampling": "without_replacement",
        "mandatory_cost": mandatory_cost, "optional_cost_total": optional_total,
        "optional_budget": optional_budget, "pool_sha256": pool_sha256,
    }
    return Instance(instance_id(n_tasks, cost_model, budget_pct, seed),
                    mandatory_cost + optional_budget, tasks, meta)


def _with_costs(instance: Instance, suffix: str, representation: str, cost, budget: int) -> Instance:
    tasks = [replace(t, cost=cost(t.cost)) for t in instance.tasks]
    mandatory_cost = sum(t.cost for t in tasks if t.mandatory)
    meta = {**instance.meta, "representation": representation, "base_instance": instance.instance_id,
            "mandatory_cost": mandatory_cost,
            "optional_cost_total": sum(t.cost for t in tasks if not t.mandatory),
            "optional_budget": budget - mandatory_cost}
    return Instance(f"{instance.instance_id}-{suffix}", budget, tasks, meta)


def represent(instance: Instance, representation: str) -> Instance:
    """Express the same instance in another time unit. Feasible selections do not change.

    x6: costs and budget times 6 (5-minute units instead of 30-minute units).
    gcd: costs divided by their greatest common divisor g, budget floor(W / g).
    Mandatory cost is a multiple of g, so the optional budget becomes floor(B / g).
    """
    if representation == "original":
        return instance
    if representation == "x6":
        return _with_costs(instance, "x6", "x6", lambda c: c * 6, instance.total_budget * 6)
    if representation == "gcd":
        g = gcd(*(t.cost for t in instance.tasks)) or 1
        normal = _with_costs(instance, "gcd", "gcd", lambda c: c // g, instance.total_budget // g)
        normal.meta["cost_divisor"] = g
        return normal
    raise ValueError(f"unknown representation {representation!r}; choose from {REPRESENTATIONS}")
