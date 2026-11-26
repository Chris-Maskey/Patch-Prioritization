import random

from patchsel.model import Instance, Task


def make_instance(rows, budget, instance_id="test"):
    """rows: (task_id, value, cost, mandatory) tuples."""
    tasks = [Task(i, v, c, m, "match" if m else "no_match") for i, v, c, m in rows]
    return Instance(instance_id, budget, tasks)


def random_instance(rng: random.Random, n: int, *, equal_cost=False, mandatory=0, budget_pct=None):
    rows = []
    for k in range(n):
        value = rng.choice([0, rng.randint(1, 100), rng.randint(1, 100), rng.randint(60, 100)])
        cost = 4 if equal_cost else rng.randint(1, 20)
        rows.append((f"T{k:02d}", value, cost, k < mandatory))
    total = sum(r[2] for r in rows)
    pct = rng.choice([0, 10, 30, 50, 100]) if budget_pct is None else budget_pct
    mandatory_cost = sum(r[2] for r in rows if r[3])
    budget = mandatory_cost + pct * (total - mandatory_cost) // 100
    return make_instance(rows, budget, f"rand-{n}")
