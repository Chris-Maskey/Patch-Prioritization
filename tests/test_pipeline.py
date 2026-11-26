import json
from pathlib import Path
import random
import unittest

from patchsel.model import Instance
from patchsel.pipeline import select
from patchsel.reference import exhaustive
from patchsel.solvers import METHODS
from patchsel.solvers.bnb import fractional_bound
from patchsel.validate import validate
from tests.helpers import make_instance, random_instance

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
EXACT = ("dp_budget", "dp_value", "bnb", "milp")


def run_all(instance):
    results = {}
    for method in METHODS:
        result = select(instance, method)
        assert validate(instance, result) == [], (method, validate(instance, result))
        results[method] = result
    return results


def optimum(instance):
    """Exhaustive optional optimum after the common preprocessing."""
    mandatory_cost = sum(t.cost for t in instance.tasks if t.mandatory)
    budget = instance.total_budget - mandatory_cost
    items = [t for t in instance.tasks if not t.mandatory and 0 < t.value and t.cost <= budget]
    return exhaustive(items, budget)[0]


class FixtureTests(unittest.TestCase):
    def test_proposal_example_scores(self):
        instance = Instance.load(FIXTURES / "proposal_example.json")
        results = run_all(instance)
        self.assertEqual(results["severity"].optional_score, 90)
        self.assertEqual(results["severity"].selected_ids, ["A", "M"])
        self.assertEqual(results["ratio"].optional_score, 160)
        self.assertEqual(results["ratio"].selected_ids, ["B", "C", "M"])
        self.assertEqual(optimum(instance), 160)

    def test_infeasible_example(self):
        instance = Instance.load(FIXTURES / "infeasible_example.json")
        for result in run_all(instance).values():
            self.assertEqual(result.status, "infeasible")
            self.assertFalse(result.feasible)
            self.assertEqual(result.shortfall, 1)
            self.assertEqual(result.selected_ids, [])


class EdgeCaseTests(unittest.TestCase):
    def test_empty_backlog(self):
        for result in run_all(make_instance([], 10)).values():
            self.assertEqual((result.status, result.optional_score, result.selected_ids), ("completed", 0, []))

    def test_zero_optional_budget(self):
        instance = make_instance([("M", 90, 5, True), ("A", 80, 1, False)], 5)
        for result in run_all(instance).values():
            self.assertEqual(result.selected_ids, ["M"])
            self.assertEqual(result.n_solver, 0)

    def test_mandatory_exactly_fills_budget_is_feasible(self):
        result = select(make_instance([("M", 90, 5, True)], 5), "ratio")
        self.assertTrue(result.feasible)

    def test_all_tasks_fit(self):
        rows = [("A", 10, 1, False), ("B", 20, 2, False), ("C", 30, 3, False)]
        for result in run_all(make_instance(rows, 6)).values():
            self.assertEqual(result.selected_ids, ["A", "B", "C"])

    def test_oversized_and_zero_value_are_deferred_before_solving(self):
        rows = [("big", 100, 11, False), ("zero", 0, 1, False), ("ok", 50, 2, False)]
        for result in run_all(make_instance(rows, 10)).values():
            self.assertEqual(result.n_solver, 1)
            self.assertEqual(result.value_sum, 50)
            self.assertEqual(result.selected_ids, ["ok"])
            self.assertEqual(result.deferred_ids, ["big", "zero"])

    def test_skip_and_continue(self):
        rows = [("A", 100, 8, False), ("B", 90, 5, False), ("C", 10, 2, False)]
        result = select(make_instance(rows, 10), "severity")
        self.assertEqual(result.selected_ids, ["A", "C"])

    def test_ties_break_by_task_id(self):
        rows = [("B", 50, 5, False), ("A", 50, 5, False)]
        for result in run_all(make_instance(rows, 5)).values():
            self.assertEqual(result.selected_ids, ["A"])

    def test_ratio_uses_exact_comparison(self):
        # 1/3 and 33/99 are equal ratios; float division gives identical values here,
        # but 100/7 > 99/7 must not tie, and equal ratios fall back to the ID.
        rows = [("Z", 33, 99, False), ("Y", 1, 3, False), ("X", 100, 7, False), ("W", 99, 7, False)]
        result = select(make_instance(rows, 3 + 7), "ratio")
        self.assertEqual(result.selected_ids, ["X", "Y"])


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.instance = make_instance([("M", 90, 2, True), ("A", 80, 3, False), ("B", 70, 3, False)], 5)
        self.result = select(self.instance, "ratio")

    def test_valid_result(self):
        self.assertEqual(validate(self.instance, self.result), [])

    def test_detects_missing_mandatory(self):
        self.result.selected_ids.remove("M")
        self.result.deferred_ids.append("M")
        self.assertIn("mandatory task missing from selection", validate(self.instance, self.result))

    def test_detects_over_budget_and_wrong_totals(self):
        self.result.selected_ids.append("B")
        self.result.deferred_ids.remove("B")
        errors = validate(self.instance, self.result)
        self.assertIn("selection exceeds the total budget", errors)
        self.assertIn("optional score does not match selection", errors)

    def test_detects_incomplete_accounting(self):
        self.result.deferred_ids.clear()
        self.assertIn("selected and deferred IDs do not cover the backlog", validate(self.instance, self.result))


class RandomisedTests(unittest.TestCase):
    """Greedy behaviour against the independent exhaustive reference."""

    def test_greedy_never_beats_optimum_and_ratio_loss_is_bounded(self):
        rng = random.Random(600)
        for trial in range(300):
            instance = random_instance(rng, rng.randint(0, 12), mandatory=rng.randint(0, 2))
            results = run_all(instance)
            if not results["ratio"].feasible:
                continue
            best = optimum(instance)
            items = [t for t in instance.tasks if not t.mandatory]
            vmax = max((t.value for t in items if t.cost <= results["ratio"].optional_budget), default=0)
            for result in results.values():
                self.assertLessEqual(result.optional_score, best, trial)
            self.assertLessEqual(best - results["ratio"].optional_score, vmax, trial)

    def test_severity_first_is_optimal_with_equal_costs(self):
        rng = random.Random(601)
        for trial in range(200):
            instance = random_instance(rng, rng.randint(0, 14), equal_cost=True)
            self.assertEqual(select(instance, "severity").optional_score, optimum(instance), trial)

    def test_exact_methods_match_exhaustive_search(self):
        rng = random.Random(603)
        for trial in range(300):
            instance = random_instance(rng, rng.randint(0, 14), mandatory=rng.randint(0, 2))
            results = run_all(instance)
            if not results["bnb"].feasible:
                continue
            best = optimum(instance)
            for method in EXACT:
                self.assertEqual(results[method].optional_score, best, (trial, method))
                self.assertEqual(results[method].proof, "optimal")

    def test_exact_methods_at_the_exhaustive_limit(self):
        rng = random.Random(602)
        for budget_pct in (10, 30, 50):
            instance = random_instance(rng, 18, budget_pct=budget_pct)
            best = optimum(instance)
            for method, result in run_all(instance).items():
                if method in EXACT:
                    self.assertEqual(result.optional_score, best, method)

    def test_equal_scores_with_different_ids_are_accepted(self):
        rows = [("A", 50, 2, False), ("B", 50, 2, False), ("C", 100, 4, False)]
        results = run_all(make_instance(rows, 4))
        self.assertEqual({results[m].optional_score for m in EXACT}, {100})


class BranchAndBoundTests(unittest.TestCase):
    def test_bound_never_underestimates_the_best_completion(self):
        rng = random.Random(604)
        for _ in range(200):
            instance = random_instance(rng, rng.randint(1, 10), budget_pct=100)
            items = [t for t in instance.tasks if t.value > 0]
            items.sort(key=lambda t: (-t.value / t.cost, t.task_id))
            values, costs = [t.value for t in items], [t.cost for t in items]
            for k in range(len(items) + 1):
                for capacity in range(0, sum(costs) + 1, 3):
                    true_best = exhaustive(items[k:], capacity)[0]
                    self.assertGreaterEqual(fractional_bound(values, costs, k, capacity), true_best)

    def test_forced_cutoff_returns_a_valid_unproven_selection(self):
        instance = random_instance(random.Random(605), 40, budget_pct=30)
        result = select(instance, "bnb", time_limit=0)
        self.assertEqual((result.status, result.proof), ("timeout", "unproven"))
        self.assertEqual(validate(instance, result), [])
        self.assertEqual(result.optional_score, select(instance, "ratio").optional_score)
        self.assertEqual(result.stats["nodes"], 0)

    def test_milp_cutoff_returns_a_valid_unproven_selection(self):
        instance = random_instance(random.Random(607), 3000, budget_pct=30)
        result = select(instance, "milp", time_limit=0.0)
        self.assertEqual((result.status, result.proof), ("timeout", "unproven"))
        self.assertEqual(validate(instance, result), [])

    def test_counts_nodes_and_pruning(self):
        result = select(random_instance(random.Random(606), 30, budget_pct=30), "bnb")
        self.assertGreater(result.stats["nodes"], 0)
        self.assertGreaterEqual(result.stats["nodes"], result.stats["pruned"])


class ResultRecordTests(unittest.TestCase):
    def test_result_record_is_json(self):
        record = select(Instance.load(FIXTURES / "proposal_example.json"), "ratio").to_dict()
        self.assertEqual(json.loads(json.dumps(record))["schema"], "cp600.result/v1")


class GrowthTests(unittest.TestCase):
    def test_growth_exponent_recovers_known_powers(self):
        from patchsel.analyze import growth_table

        cell = {"cost_model": "uniform", "budget_pct": 30, "instances": 5, "completed": 5}
        summary = [{**cell, "method": "dp_budget", "n_tasks": n, "runtime_ms_median": 3e-5 * n * n}
                   for n in (250, 500, 1000, 2000)]
        summary += [{**cell, "method": "ratio", "n_tasks": n, "runtime_ms_median": 0.01 * n}
                    for n in (50, 250, 500, 1000)]  # N=50 is below the fitted range
        summary += [{**cell, "method": "bnb", "n_tasks": n, "runtime_ms_median": 1.0,
                     "completed": 4 if n == 1000 else 5} for n in (250, 500, 1000)]
        exponents = {r["method"]: r["exponent"] for r in growth_table(summary)}
        self.assertEqual(exponents, {"dp_budget": 2.0, "ratio": 1.0})  # bnb: incomplete cell dropped


if __name__ == "__main__":
    unittest.main()


class KevPolicyTests(unittest.TestCase):
    def test_reservation_cost_and_dropped_kev_tasks(self):
        from patchsel.compare import kev_policy

        # W=5: reserving the KEV task (value 10) leaves no room for the 90-point task.
        instance = make_instance([("K", 10, 5, True), ("A", 90, 5, False)], 5)
        row = kev_policy(instance)
        self.assertEqual((row["reserved_score"], row["unreserved_score"]), (10, 90))
        self.assertEqual((row["score_cost"], row["kev_kept_unreserved"]), (80, 0))
