# CP600 Group 4: budget-constrained patch selection

Python command-line experiment that compares five methods for choosing vulnerability patches under a fixed effort budget. KEV-matched tasks are mandatory. Their cost is reserved first. The methods select optional tasks with the remaining budget.

Status: complete. The final report is `report/report.tex`; its numbers and figures come from `results/`.

| Method | `--method` | Result |
| --- | --- | --- |
| Severity-first greedy | `severity` | Heuristic |
| Benefit-per-cost greedy | `ratio` | Heuristic |
| Budget-based DP | `dp_budget` | Exact |
| Value-based DP | `dp_value` | Exact |
| Branch and bound | `bnb` | Exact, or unproven after `--time-limit` |
| *Reference from prior work:* integer programming (HiGHS via SciPy) | `milp` | Exact, or unproven after `--time-limit` |

## Download

**Code.** Clone this repository:

```sh
git clone <CODE-REPOSITORY-URL>              # TODO: add the code link
cd <repository-folder>
```

**Dataset.** The prepared evaluation pool (`data/prepared/pool.csv`, 4,436 vulnerability groups, with `pool_meta.json`) is in the repository. The larger files are in one archive, `cp600-dataset-v1.0.zip`, at <DATASET-URL> (TODO: add the dataset link). Unzip it in the repository root:

```sh
curl -LO <DATASET-URL>/cp600-dataset-v1.0.zip  # TODO: add the dataset link
unzip cp600-dataset-v1.0.zip                 # adds data/raw/, data/instances/, results/main/benchmark.jsonl.gz
gunzip results/main/benchmark.jsonl.gz
```

| Path | Content | Where | Needed for |
| --- | --- | --- | --- |
| `data/prepared/pool.csv`, `pool_meta.json` | Evaluation pool and its hashes | Repository | `generate`, `bench`, `compare` |
| `data/raw/pypi.zip`, `data/raw/kev.json` | OSV PyPI snapshot and CISA KEV catalogue 2026.11.03 | Release | `prepare` and `check_data.py` (they check the SHA-256 hashes in `pool_meta.json`) |
| `data/instances/` | The 351 benchmark instances as JSON | Release | Optional: `bench` regenerates them from the pool |
| `results/main/benchmark.jsonl` | The 5,438 raw benchmark rows | Release (gzipped) | `analyze` on the main benchmark |

The tests, `solve`, `generate`, `bench`, and `compare` work from the repository alone. The live OSV download changes every day, so use the snapshots in the release to rebuild the pool.

**Data sources and licences.** Vulnerability records come from [OSV](https://osv.dev) (PyPI ecosystem: PyPI Advisory Database, GitHub Advisory Database, and Python Software Foundation records, each under CC BY 4.0). Exploitation status comes from the [CISA Known Exploited Vulnerabilities catalogue](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) (CC0 1.0). CISA does not endorse this project.

## Run

Requires [uv](https://docs.astral.sh/uv/). uv installs Python 3.13, `cvss==3.6`, `matplotlib`, and `scipy` on the first run.

```sh
uv run check_data.py --self-test          # audit rules self-test
uv run python -m patchsel prepare         # data/raw -> data/prepared/pool.csv
uv run python -m patchsel generate --n 500 --cost-model uniform --budget-pct 30 --seed 0
uv run python -m patchsel solve data/instances/N0500-uniform-b30-s0.json --time-limit 10 --out results/run.jsonl
uv run python -m patchsel solve fixtures/proposal_example.json --show-ids
uv run python -m unittest                 # test suite (about 1 second)
uv run python -m patchsel bench --sizes 100 --seeds 0 --out results/pilot/small.jsonl
uv run python -m patchsel analyze results/main/benchmark.jsonl --units results/units/units.jsonl --out results/figures
uv run python -m patchsel compare --out results/compare   # prior-work comparisons, about 2 minutes
```

`solve` validates every result against its instance and exits with status 1 if a check fails. Without `--time-limit`, branch and bound can run for a very long time on large backlogs.

The tests compare the three exact methods and HiGHS with exhaustive search on up to 18 optional tasks. They also check that the branch-and-bound bound never underestimates the best completion, and that a forced cutoff returns a valid selection that is marked unproven.

## Benchmark runner

`bench` generates each instance in the grid, then runs one method at a time in a separate worker process. The defaults follow the proposal: all cost models, budgets of 10/30/50%, seeds 0–4, 3 repeats, 10 s, and 1 GiB.

- The worker measures only the selection time. Branch and bound stops itself at the time limit and keeps its best selection. A method that finishes over the limit gets `timeout`. The parent kills a worker that is still running 3 s after the limit.
- The parent polls the worker's memory and kills it above the limit (`memory_limit`). `peak_rss_bytes` comes from the kernel's rusage for the worker.
- A run repeats only if it completed. Limit-stopped and failed runs run once.
- Each run is appended as one JSON line when it ends. If you run the same command again, it continues and skips the recorded runs.
- `<out>.env.json` records the Python version, OS, CPU, and limits.

Each row has the instance settings, the result record, `repeat`, `peak_rss_bytes`, `selection` (false when the worker was killed), and `valid`.

| Run | Command |
| --- | --- |
| Main benchmark (task 10) | `bench --sizes 50 100 250 500 1000 2000 4436 --out results/main/benchmark.jsonl` |
| Time units (task 11) | `bench --sizes 250 1000 --seeds 0 --methods dp_budget dp_value bnb --representations original x6 gcd --out results/units/units.jsonl` |

`--representations` runs each instance in 30-minute units (`original`), with costs and budget ×6 (`x6`), and with costs divided by their greatest common divisor (`gcd`).

`analyze` writes `summary.csv` (one row for each size, cost model, budget and method), `growth.csv` (the fitted growth exponent of selection time in N for each method and cost model, Table 4 of the report), `reconcile.json` (missing runs, invalid selections), the report figures (PDF and PNG), and, with `--units`, `units.csv`. It fails if two exact methods certify different optimal scores for one instance.

## Comparison with prior work

`compare` writes to `results/compare/`:

- `goohs_runs.csv` and `goohs_summary.csv` contain 320 synthetic instances in the setting of Goohs et al.: 600 vulnerabilities, hazard 6–100, cost 10–100, 40 samples per budget, budgets of 2–90% of total cost. The file compares random patching, severity-first and benefit-per-cost against the exact optimum. The budget-based DP gives the optimum, and HiGHS checks it on every instance. `fig6_goohs_replication.pdf` plots the result.
- `jacobs_thresholds.csv` gives the coverage and efficiency of CVSS-threshold rules against the KEV-matched groups in the pool, for comparison with Table 2 of Jacobs et al.
- `kev_policy.csv` gives the score cost of the KEV-first policy: for each benchmark instance with KEV tasks, the HiGHS optimum at the same total budget with KEV work reserved and with KEV tasks scored like any other task, and how many KEV tasks the unreserved plan keeps.

The `milp` method runs the integer-programming approach of prior studies inside the benchmark. Its worker loads SciPy before the timer starts. The other methods never load SciPy, so their memory figures are not affected.

## Data contract

All costs are positive integers in 30-minute units. All values are CVSS 3.1 base scores in tenths (9.8 → 98).

### Pool row (`data/prepared/pool.csv`)

One row per consistent OSV alias group. The file has 4,436 rows, and 17 of them are KEV matches. These counts match `data/feasibility.json`.

| Field | Meaning |
| --- | --- |
| `group_id` | Stable task ID: the smallest OSV record ID in the group |
| `value` | Score in tenths, 0–100 |
| `kev_status` | `match`: a CVE alias is in KEV. `no_match`: the group has CVEs, but none is in KEV. `no_cve`: the group has no CVE, so we cannot check KEV. |
| `cve_ids` | CVE aliases, separated by `;` |
| `osv_ids` | OSV record IDs in the group, separated by `;` |

`pool_meta.json` records the pool SHA-256, the source snapshot hashes, the KEV catalog version, and the rules.

### Instance (`data/instances/<instance_id>.json`, schema `cp600.instance/v1`)

- **ID:** `N{size:04d}-{cost_model}-b{budget_pct:02d}-s{seed}`, for example `N0500-uniform-b30-s0`.
- **Sampling:** `N` groups without replacement. The sample depends only on `(N, seed)`, so each cost model and budget uses the same groups.
- **Costs:** `equal` = 4. `uniform` = random integer 1–20. `correlated` = `max(1, ceil(value/5) + jitter)`, jitter ∈ {−1, 0, 1}.
- **Budget:** optional budget `B = floor(budget_pct × total optional cost / 100)`. Total budget `W = mandatory cost + B`.
- **Tasks:** rows of `[task_id, value, cost, mandatory, kev_status]`, sorted by `task_id`.

### Result record (JSON lines, schema `cp600.result/v1`)

One record per method per instance. Main fields:

| Field | Meaning |
| --- | --- |
| `status` | `completed`, `infeasible`, `timeout`, `memory_limit`, or `error` (the last three come from the runner) |
| `feasible`, `shortfall` | `feasible` is false only when the mandatory cost exceeds `W`. `shortfall` = mandatory cost − `W`. |
| `proof` | `optimal`, `heuristic`, `unproven` (branch and bound stopped at a cutoff), or `none` |
| `n_solver`, `value_sum` | `n` and `P` after preprocessing. Preprocessing defers tasks with cost > `B` and tasks with zero value. |
| `selected_ids`, `deferred_ids` | Together they contain each task exactly once. Mandatory tasks are always selected. |
| `optional_score`, `optional_cost`, `total_cost` | Totals for the selection |
| `runtime_ns` | Measured from mandatory reservation to selection recovery. Instance loading is not included. |
| `stats` | Counters for each method. Greedy: `skipped`. DP: `table_cells` (n·(B+1) or n·(P+1)) and `updates`. Branch and bound: `nodes`, `pruned`, `greedy_score`, `improved_on_greedy`. |

Example (proposal example, benefit-per-cost greedy):

```json
{"schema": "cp600.result/v1", "instance_id": "proposal-example", "method": "ratio", "status": "completed",
 "feasible": true, "proof": "heuristic", "total_budget": 8, "mandatory_cost": 2, "shortfall": 0,
 "optional_budget": 6, "n_tasks": 4, "n_mandatory": 1, "n_optional": 3, "n_solver": 3, "value_sum": 250,
 "selected_ids": ["B", "C", "M"], "deferred_ids": ["A"], "optional_score": 160, "optional_cost": 6,
 "total_cost": 8, "mandatory_included": true, "runtime_ns": 8000, "stats": {"skipped": 1}}
```

### Solver interface

Use `patchsel/solvers/greedy.py` as the model for a new method. Register the method in `patchsel/solvers/__init__.py`. A solver receives `(items, budget)`. `items` contains the preprocessed optional tasks, sorted by ID. The solver returns `Solution(chosen_indices, proof, stats)`. The shared pipeline (`patchsel/pipeline.py`) does the mandatory reservation, preprocessing, accounting, and timing.

## Layout

| Path | Purpose |
| --- | --- |
| `check_data.py` | Source snapshot audit, which writes `data/feasibility.json` |
| `patchsel/osv.py` | Alias grouping and CVSS eligibility rules, shared by the audit and `prepare` |
| `patchsel/prepare.py`, `patchsel/instances.py` | Pool build and seeded instance generation |
| `patchsel/pipeline.py`, `patchsel/validate.py` | Common selection pipeline and independent result checks |
| `patchsel/solvers/` | Selection methods |
| `patchsel/reference.py` | Exhaustive search (≤ 18 items), used only in tests |
| `patchsel/runner.py` | Benchmark runner and worker process |
| `patchsel/analyze.py` | Summary tables, paired win/tie/loss counts, and report figures |
| `patchsel/compare.py` | Repeats of Goohs et al. (WEIS 2022) and Jacobs et al. (2020), scores only |
| `report/report.tex` | Final report (LaTeX; figures from `results/figures`) |
| `fixtures/` | Hand-calculated proposal example and an infeasible case |
| `results/` | Benchmark output (JSON lines, environment, logs) |
