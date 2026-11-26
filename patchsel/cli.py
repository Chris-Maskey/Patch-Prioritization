"""Command-line interface: python -m patchsel {prepare,generate,solve,bench,analyze,compare}."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from patchsel.instances import COST_MODELS, REPRESENTATIONS
from patchsel.model import Instance
from patchsel.runner import TIME_LIMITED
from patchsel.solvers import METHODS

INSTANCES = Path(__file__).resolve().parent.parent / "data" / "instances"


def cmd_prepare(args) -> int:
    from patchsel.prepare import build_pool, write_pool

    rows, summary = build_pool()
    summary = write_pool(rows, summary)
    print(f"Wrote {summary['rows']} pool rows ({summary['kev_status']}) "
          f"sha256={summary['sha256'][:12]}… to data/prepared/pool.csv")
    return 0


def cmd_generate(args) -> int:
    from patchsel.instances import generate
    from patchsel.prepare import POOL, POOL_META, load_pool

    if not POOL.exists():
        raise SystemExit("data/prepared/pool.csv is missing; run `python -m patchsel prepare` first")
    pool_sha = json.loads(POOL_META.read_text())["sha256"]
    instance = generate(load_pool(), args.n, args.cost_model, args.budget_pct, args.seed, pool_sha)
    out = args.out or INSTANCES / f"{instance.instance_id}.json"
    instance.save(out)
    m = instance.meta
    print(f"{instance.instance_id}: {len(instance.tasks)} tasks, "
          f"{sum(t.mandatory for t in instance.tasks)} mandatory (cost {m['mandatory_cost']}), "
          f"W={instance.total_budget}, B={m['optional_budget']} -> {out}")
    return 0


def cmd_solve(args) -> int:
    from patchsel.pipeline import select
    from patchsel.validate import validate

    instance = Instance.load(args.instance)
    methods = list(METHODS) if args.method == "all" else [args.method]
    if "milp" in methods:
        import scipy.optimize  # noqa: F401  load before the timer starts
    results, failures = [], 0
    for method in methods:
        options = ({"time_limit": args.time_limit}
                   if method in TIME_LIMITED and args.time_limit is not None else {})
        result = select(instance, method, **options)
        errors = validate(instance, result)
        failures += bool(errors)
        results.append((result, errors))

    first = results[0][0]
    print(f"{instance.instance_id}: {first.n_tasks} tasks, {first.n_mandatory} mandatory "
          f"(cost {first.mandatory_cost}), W={first.total_budget}, B={first.optional_budget}, "
          f"solver input n={first.n_solver}, P={first.value_sum}")
    if not first.feasible:
        print(f"INFEASIBLE: mandatory work exceeds the budget by {first.shortfall} units")
    print(f"{'method':<10} {'status':<11} {'proof':<10} {'score':>7} {'opt cost':>9} "
          f"{'selected':>9} {'valid':>6} {'ms':>8}")
    for result, errors in results:
        print(f"{result.method:<10} {result.status:<11} {result.proof:<10} {result.optional_score:>7} "
              f"{result.optional_cost:>9} {len(result.selected_ids):>9} "
              f"{'yes' if not errors else 'NO':>6} {result.runtime_ns / 1e6:>8.3f}")
        for error in errors:
            print(f"  ! {error}")
        if args.show_ids:
            print(f"  selected: {' '.join(result.selected_ids) or '-'}")
            print(f"  deferred: {' '.join(result.deferred_ids) or '-'}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("a") as handle:
            for result, _ in results:
                handle.write(json.dumps(result.to_dict()) + "\n")
        print(f"Appended {len(results)} result record(s) to {args.out}")
    return 1 if failures else 0


def cmd_bench(args) -> int:
    from patchsel.instances import generate, represent
    from patchsel.prepare import POOL_META, load_pool
    from patchsel.runner import run_grid

    pool, pool_sha = load_pool(), json.loads(POOL_META.read_text())["sha256"]
    instances = []
    for n in args.sizes:
        for model in args.cost_models:
            for pct in args.budgets:
                for seed in args.seeds:
                    base = generate(pool, n, model, pct, seed, pool_sha)
                    for representation in args.representations:
                        instance = represent(base, representation)
                        path = INSTANCES / f"{instance.instance_id}.json"
                        if not path.exists():
                            instance.save(path)
                        instances.append((instance, path))
    run_grid(instances, args.methods, args.out, repeats=args.repeats,
             time_limit=args.time_limit, memory_limit=args.memory_mib * 2**20)
    print(f"Results in {args.out}; environment in {args.out.with_suffix('.env.json')}")
    return 0


def cmd_analyze(args) -> int:
    from patchsel.analyze import analyze

    report = analyze(args.results, args.out, args.units)
    print(f"{report['rows']} rows, {report['instances']} instances, {report['runs']} runs; "
          f"{len(report['missing_runs'])} missing, {len(report['invalid_selections'])} invalid, "
          f"{report['instances_with_proven_optimum']} instances with a proven optimum")
    print(f"Wrote summary.csv, growth.csv, reconcile.json, and {len(report['figures'])} figure files to {args.out}")
    return 1 if report["missing_runs"] or report["invalid_selections"] else 0


def cmd_compare(args) -> int:
    from patchsel.compare import compare

    report = compare(args.out, args.samples)
    print(f"Goohs et al. setting: {report['goohs_instances']} instances (DP optimum checked with HiGHS)")
    for row in report["goohs_summary"]:
        print(f"  budget {row['budget_pct']:>2}%  {row['method']:<8} median {row['median_pct_of_optimum']:>6}% "
              f"of optimum (min {row['min_pct_of_optimum']}, max {row['max_pct_of_optimum']})")
    print("Jacobs et al. thresholds against KEV in our pool:")
    for row in report["jacobs"]:
        print(f"  {row['rule']:<32} effort {row['level_of_effort']!s:>5}  coverage {row['coverage_pct']!s:>6}%  "
              f"efficiency {row['efficiency_pct']}%")
    kev = report["kev_policy"]
    costly = [r for r in kev if r["score_cost"] > 0]
    print(f"KEV-first policy at the same total budget: {len(kev)} instances with KEV tasks, "
          f"{len(costly)} lose score, largest loss {max(r['score_cost_pct'] for r in kev)}%")
    print(f"Wrote CSV files and figures to {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m patchsel", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("prepare", help="build data/prepared/pool.csv from the saved snapshots")

    gen = sub.add_parser("generate", help="write one seeded instance")
    gen.add_argument("--n", type=int, required=True, help="backlog size N")
    gen.add_argument("--cost-model", choices=COST_MODELS, required=True)
    gen.add_argument("--budget-pct", type=int, required=True, help="optional budget, %% of optional cost")
    gen.add_argument("--seed", type=int, required=True)
    gen.add_argument("--out", type=Path)

    solve = sub.add_parser("solve", help="run methods on an instance and validate the results")
    solve.add_argument("instance", type=Path)
    solve.add_argument("--method", choices=[*METHODS, "all"], default="all")
    solve.add_argument("--show-ids", action="store_true")
    solve.add_argument("--time-limit", type=float, help="cutoff in seconds for bnb and milp")
    solve.add_argument("--out", type=Path, help="append result records as JSON lines")

    bench = sub.add_parser("bench", help="run a grid in isolated workers with time and memory limits")
    bench.add_argument("--sizes", type=int, nargs="+", required=True)
    bench.add_argument("--cost-models", nargs="+", choices=COST_MODELS, default=list(COST_MODELS))
    bench.add_argument("--budgets", type=int, nargs="+", default=[10, 30, 50])
    bench.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    bench.add_argument("--methods", nargs="+", choices=list(METHODS), default=list(METHODS))
    bench.add_argument("--repeats", type=int, default=3, help="timed repeats for completed runs")
    bench.add_argument("--representations", nargs="+", choices=REPRESENTATIONS, default=["original"],
                       help="time-unit variants of each instance (task 11)")
    bench.add_argument("--time-limit", type=float, default=10.0, help="selection time limit, seconds")
    bench.add_argument("--memory-mib", type=int, default=1024, help="worker memory limit, MiB")
    bench.add_argument("--out", type=Path, required=True, help="JSON lines file; reruns resume it")

    analyze = sub.add_parser("analyze", help="summary tables and report figures from bench rows")
    analyze.add_argument("results", type=Path)
    analyze.add_argument("--units", type=Path, help="task 11 rows (bench --representations)")
    analyze.add_argument("--out", type=Path, required=True)

    comp = sub.add_parser("compare", help="repeat the Goohs et al. and Jacobs et al. comparisons")
    comp.add_argument("--out", type=Path, required=True)
    comp.add_argument("--samples", type=int, default=40, help="samples per budget (Goohs et al. used 40)")

    args = parser.parse_args(argv)
    return {"prepare": cmd_prepare, "generate": cmd_generate, "solve": cmd_solve,
            "bench": cmd_bench, "analyze": cmd_analyze, "compare": cmd_compare}[args.command](args)
