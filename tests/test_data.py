import json
from pathlib import Path
import unittest

import random

from patchsel.instances import COST_MODELS, generate, represent
from patchsel.reference import exhaustive
from patchsel.model import Instance
from patchsel.prepare import POOL, POOL_META, load_pool

SMALL_POOL = [
    {"group_id": f"G{k:03d}", "value": (k * 37) % 101, "kev_status": "match" if k % 10 == 0 else "no_match"}
    for k in range(200)
]


class InstanceGenerationTests(unittest.TestCase):
    def test_same_seed_reproduces_instance(self):
        a = generate(SMALL_POOL, 50, "uniform", 30, 3)
        b = generate(SMALL_POOL, 50, "uniform", 30, 3)
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertNotEqual(a.to_dict()["tasks"], generate(SMALL_POOL, 50, "uniform", 30, 4).to_dict()["tasks"])

    def test_cost_models_share_the_same_sample(self):
        ids = {model: [t.task_id for t in generate(SMALL_POOL, 40, model, 10, 1).tasks] for model in COST_MODELS}
        self.assertEqual(len({tuple(v) for v in ids.values()}), 1)
        self.assertEqual(len(set(ids["equal"])), 40)

    def test_costs_and_budget_follow_the_proposal(self):
        for model in COST_MODELS:
            for pct in (0, 10, 30, 50):
                inst = generate(SMALL_POOL, 120, model, pct, 2)
                optional = sum(t.cost for t in inst.tasks if not t.mandatory)
                mandatory = sum(t.cost for t in inst.tasks if t.mandatory)
                self.assertEqual(inst.total_budget, mandatory + pct * optional // 100)
                for t in inst.tasks:
                    self.assertGreaterEqual(t.cost, 1)
                    if model == "equal":
                        self.assertEqual(t.cost, 4)
                    elif model == "uniform":
                        self.assertLessEqual(t.cost, 20)
                    else:
                        base = -(-t.value // 5)
                        self.assertIn(t.cost, {max(1, base + d) for d in (-1, 0, 1)})
                    self.assertEqual(t.mandatory, t.kev_status == "match")

    def test_round_trip(self):
        inst = generate(SMALL_POOL, 30, "correlated", 50, 0)
        self.assertEqual(Instance.from_dict(json.loads(json.dumps(inst.to_dict()))).to_dict(), inst.to_dict())

    def test_rejects_bad_parameters(self):
        with self.assertRaises(ValueError):
            generate(SMALL_POOL, 201, "equal", 10, 0)
        with self.assertRaises(ValueError):
            generate(SMALL_POOL, 10, "lognormal", 10, 0)


class RepresentationTests(unittest.TestCase):
    @staticmethod
    def optimum(instance):
        mandatory = sum(t.cost for t in instance.tasks if t.mandatory)
        budget = instance.total_budget - mandatory
        items = [t for t in instance.tasks if not t.mandatory and t.value and t.cost <= budget]
        return exhaustive(items, budget)[0]

    def test_representations_keep_the_optimum(self):
        rng = random.Random(800)
        for _ in range(100):
            model = rng.choice(COST_MODELS)
            base = generate(SMALL_POOL, rng.randint(1, 14), model, rng.choice([10, 30, 50]), rng.randint(0, 99))
            for name in ("x6", "gcd"):
                variant = represent(base, name)
                self.assertEqual(self.optimum(variant), self.optimum(base), (base.instance_id, name))
                self.assertEqual([t.task_id for t in variant.tasks], [t.task_id for t in base.tasks])

    def test_x6_and_gcd_change_the_budget_as_expected(self):
        base = generate(SMALL_POOL, 50, "equal", 30, 0)
        scaled, normal = represent(base, "x6"), represent(base, "gcd")
        self.assertEqual(scaled.total_budget, 6 * base.total_budget)
        self.assertEqual(normal.meta["cost_divisor"], 4)
        self.assertEqual(normal.meta["optional_budget"], base.meta["optional_budget"] // 4)
        self.assertEqual(represent(scaled, "gcd").total_budget, normal.total_budget)
        self.assertEqual(scaled.instance_id, base.instance_id + "-x6")


class PriorWorkComparisonTests(unittest.TestCase):
    def test_threshold_rules_count_kev_coverage_and_efficiency(self):
        from patchsel.compare import jacobs_rows

        pool = [{"group_id": "a", "value": 100, "kev_status": "match"},
                {"group_id": "b", "value": 95, "kev_status": "no_match"},
                {"group_id": "c", "value": 72, "kev_status": "match"},
                {"group_id": "d", "value": 40, "kev_status": "no_cve"}]
        rows = {r["rule"]: r for r in jacobs_rows(pool)}
        self.assertEqual((rows["CVSS 10+"]["level_of_effort"], rows["CVSS 10+"]["coverage_pct"]), (1, 50.0))
        self.assertEqual((rows["CVSS 9+"]["kev_covered"], rows["CVSS 9+"]["efficiency_pct"]), (1, 50.0))
        self.assertEqual((rows["CVSS 7+"]["coverage_pct"], rows["CVSS 7+"]["efficiency_pct"]), (100.0, 66.67))
        self.assertEqual(rows["Random (by chance)"]["efficiency_pct"], 50.0)

    def test_random_fill_respects_the_budget(self):
        from patchsel.compare import _random_fill
        from patchsel.model import Task

        items = [Task(f"T{k}", 10 + k, 1 + k % 5, False) for k in range(30)]
        rng = random.Random(1)
        for budget in (0, 7, 40, 1000):
            score = _random_fill(items, budget, rng)
            self.assertLessEqual(score, sum(t.value for t in items))
            if budget >= sum(t.cost for t in items):
                self.assertEqual(score, sum(t.value for t in items))


@unittest.skipUnless(POOL.exists(), "run `python -m patchsel prepare` first")
class PreparedPoolTests(unittest.TestCase):
    def test_pool_matches_the_audit(self):
        pool = load_pool()
        meta = json.loads(POOL_META.read_text())
        audit = json.loads((POOL.parent.parent / "feasibility.json").read_text())["counts"]
        self.assertEqual(len(pool), audit["consistent_unique_groups"])
        self.assertEqual(sum(r["kev_status"] == "match" for r in pool), audit["consistent_kev_groups"])
        self.assertEqual(len({r["group_id"] for r in pool}), len(pool))
        self.assertTrue(all(0 <= r["value"] <= 100 for r in pool))
        self.assertTrue(all((r["kev_status"] == "no_cve") == (r["cve_ids"] == "") for r in pool))
        self.assertEqual(meta["rows"], len(pool))


if __name__ == "__main__":
    unittest.main()
