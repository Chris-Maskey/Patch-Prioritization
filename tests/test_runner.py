import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest import mock

from patchsel import runner
from tests.helpers import random_instance

GIB = 2**30


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.instance = random_instance(random.Random(700), 30, budget_pct=30)
        self.path = Path(self.tmp.name) / "instance.json"
        self.instance.save(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def run_once(self, method, time_limit=10.0, memory_limit=GIB):
        return runner.run_once(self.instance, self.path, method, time_limit, memory_limit)

    def test_completed_run_is_validated(self):
        row = self.run_once("dp_budget")
        self.assertEqual((row["status"], row["proof"], row["valid"]), ("completed", "optimal", True))
        self.assertGreater(row["peak_rss_bytes"], 0)

    def test_large_result_does_not_block_the_worker(self):
        instance = random_instance(random.Random(701), 5000, budget_pct=10)
        path = Path(self.tmp.name) / "large.json"
        instance.save(path)
        row = runner.run_once(instance, path, "severity", 10.0, GIB)
        self.assertEqual((row["status"], row["valid"]), ("completed", True))

    def test_finishing_over_the_limit_is_a_timeout(self):
        row = self.run_once("dp_value", time_limit=0)
        self.assertEqual(row["status"], "timeout")
        self.assertTrue(row["selection"] and row["valid"])

    def test_bnb_cutoff_keeps_its_incumbent(self):
        row = self.run_once("bnb", time_limit=0)
        self.assertEqual((row["status"], row["proof"], row["valid"]), ("timeout", "unproven", True))

    def test_hard_kill_is_a_timeout_without_selection(self):
        with mock.patch.object(runner, "STARTUP_GRACE", 0.0):
            row = self.run_once("dp_budget", time_limit=0)
        self.assertEqual((row["status"], row["selection"]), ("timeout", False))

    def test_memory_limit_kills_the_worker(self):
        row = self.run_once("dp_budget", memory_limit=1)
        self.assertEqual((row["status"], row["selection"]), ("memory_limit", False))

    def test_worker_error_is_reported(self):
        row = self.run_once("no_such_method")
        self.assertEqual(row["status"], "error")
        self.assertIn("no_such_method", row["error"])

    def test_grid_resumes_and_repeats_only_completed_runs(self):
        out = Path(self.tmp.name) / "results.jsonl"
        grid = dict(repeats=3, time_limit=0, memory_limit=GIB, log=lambda _: None)
        runner.run_grid([(self.instance, self.path)], ["severity"], out, **grid)
        runner.run_grid([(self.instance, self.path)], ["severity"], out, **grid)
        rows = [json.loads(line) for line in out.read_text().splitlines()]
        self.assertEqual([r["repeat"] for r in rows], [0])  # timed out once, not repeated
        self.assertTrue(out.with_suffix(".env.json").exists())


if __name__ == "__main__":
    unittest.main()
