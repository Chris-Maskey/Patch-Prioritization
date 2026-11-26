"""Comparisons with prior work (scores only; nothing here is timed).

1. Goohs et al. (WEIS 2022) solve CVSS-weighted patch selection as a knapsack and
   compare the exact plan with random ("oblivious") patching on synthetic data:
   hazards uniform on 6..100, costs uniform on 10..100, 40 samples per budget.
   We repeat that setting and add severity-first and benefit-per-cost greedy.
2. Jacobs et al. (J. Cybersecurity 2020, Table 2) measure how well CVSS-threshold
   rules cover exploited vulnerabilities. We measure the same rules against the
   KEV-matched groups in our pool.
3. The score cost of our KEV-first policy: on the benchmark instances, at the same
   total budget W, the optimum with KEV work reserved against the optimum when KEV
   tasks are scored like any other task.
"""

from __future__ import annotations

from pathlib import Path
import random
from statistics import median

from patchsel.analyze import COLORS, COST_MODELS, LABELS, MUTED, _save, _style, write_csv
from patchsel.model import Task
from patchsel.solvers import METHODS

GOOHS_ITEMS = 600
GOOHS_SAMPLES = 40
GOOHS_HAZARD = (6, 100)
GOOHS_COST = (10, 100)
BUDGET_SHARES = [2, 5, 10, 20, 30, 50, 70, 90]  # percent of total cost
KEV_GRID = {"sizes": (50, 100, 250, 500, 1000, 2000, 4436), "budgets": (10, 30, 50),
            "seeds": (0, 1, 2, 3, 4)}  # the main benchmark grid
RANDOM_COLOR = "#8a8984"  # neutral: a baseline, not one of the compared methods


def _random_fill(items: list[Task], budget: int, rng: random.Random) -> int:
    """Oblivious patching: a random order, then skip-and-continue."""
    order = list(range(len(items)))
    rng.shuffle(order)
    score, remaining = 0, budget
    for i in order:
        if items[i].cost <= remaining:
            remaining -= items[i].cost
            score += items[i].value
    return score


def goohs_rows(samples: int = GOOHS_SAMPLES, seed: int = 2022) -> list[dict]:
    rows = []
    for share in BUDGET_SHARES:
        for sample in range(samples):
            rng = random.Random(f"goohs|{share}|{sample}|{seed}")
            items = [Task(f"V{k:03d}", rng.randint(*GOOHS_HAZARD), rng.randint(*GOOHS_COST), False)
                     for k in range(GOOHS_ITEMS)]
            budget = share * sum(t.cost for t in items) // 100
            optimum = sum(items[i].value for i in METHODS["dp_budget"](items, budget).chosen)
            check = sum(items[i].value for i in METHODS["milp"](items, budget).chosen)
            if check != optimum:
                raise RuntimeError(f"DP and HiGHS disagree at share {share}, sample {sample}")
            scores = {
                "random": _random_fill(items, budget, rng),
                "severity": sum(items[i].value for i in METHODS["severity"](items, budget).chosen),
                "ratio": sum(items[i].value for i in METHODS["ratio"](items, budget).chosen),
            }
            for method, score in scores.items():
                rows.append({"budget_pct": share, "sample": sample, "method": method,
                             "score": score, "optimum": optimum,
                             "pct_of_optimum": round(100 * score / optimum, 4)})
    return rows


def goohs_summary(rows: list[dict]) -> list[dict]:
    table = []
    for share in BUDGET_SHARES:
        for method in ("random", "severity", "ratio"):
            values = sorted(r["pct_of_optimum"] for r in rows
                            if r["budget_pct"] == share and r["method"] == method)
            table.append({"budget_pct": share, "method": method, "samples": len(values),
                          "median_pct_of_optimum": round(median(values), 2),
                          "min_pct_of_optimum": round(values[0], 2),
                          "max_pct_of_optimum": round(values[-1], 2)})
    return table


def goohs_figure(summary: list[dict], out: Path) -> list[Path]:
    plt = _style()
    fig, ax = plt.subplots(figsize=(4.6, 3.0))  # printed at 0.7 of the 6.5 in text width
    ax.axhline(100, color=MUTED, linewidth=1)
    ax.text(BUDGET_SHARES[-1], 102.5, "exact optimum = 100 (DP, checked with HiGHS)", fontsize=7,
            color=MUTED, va="bottom", ha="right")
    styles = {"random": (RANDOM_COLOR, "X", "Random (oblivious) patching"),
              "severity": (COLORS["severity"], "o", LABELS["severity"]),
              "ratio": (COLORS["ratio"], "s", LABELS["ratio"])}
    for method, (color, marker, label) in styles.items():
        points = [r for r in summary if r["method"] == method]
        xs = [r["budget_pct"] for r in points]
        ax.fill_between(xs, [r["min_pct_of_optimum"] for r in points],
                        [r["max_pct_of_optimum"] for r in points], color=color, alpha=0.1, linewidth=0)
        ax.plot(xs, [r["median_pct_of_optimum"] for r in points], color=color, marker=marker,
                markersize=6, markeredgecolor="#fcfcfb", markeredgewidth=1.5, label=label)
    ax.set_xlabel("Budget (% of total patching cost)")
    ax.set_ylabel("Score (% of exact optimum)")
    ax.set_ylim(0, 110)
    ax.legend(loc="lower right")
    fig.tight_layout()
    paths = _save(fig, out, "fig6_goohs_replication")
    plt.close(fig)
    return paths


def jacobs_rows(pool: list[dict]) -> list[dict]:
    """CVSS-threshold rules against the KEV-matched groups in the pool."""
    kev = sum(row["kev_status"] == "match" for row in pool)
    rows = []
    for threshold in (10, 9, 8, 7, 6, 5, 4):
        chosen = [row for row in pool if row["value"] >= threshold * 10]
        hits = sum(row["kev_status"] == "match" for row in chosen)
        rows.append({"rule": f"CVSS {threshold}+", "level_of_effort": len(chosen),
                     "effort_pct_of_pool": round(100 * len(chosen) / len(pool), 2),
                     "kev_covered": hits, "coverage_pct": round(100 * hits / kev, 2),
                     "efficiency_pct": round(100 * hits / len(chosen), 2) if chosen else 0.0})
    rows.append({"rule": "KEV first (our mandatory policy)", "level_of_effort": kev,
                 "effort_pct_of_pool": round(100 * kev / len(pool), 2), "kev_covered": kev,
                 "coverage_pct": 100.0, "efficiency_pct": 100.0})
    rows.append({"rule": "Random (by chance)", "level_of_effort": "", "effort_pct_of_pool": "",
                 "kev_covered": "", "coverage_pct": "",
                 "efficiency_pct": round(100 * kev / len(pool), 2)})
    return rows


def kev_policy(instance) -> dict:
    """Score cost of reserving KEV work first, at the instance's total budget W.

    "Reserved" is the benchmark policy: every KEV task is kept and HiGHS fills the rest
    of W. "Unreserved" scores KEV tasks like any other task and HiGHS fills W. Both
    totals include KEV values.
    """
    from dataclasses import replace

    from patchsel.model import Instance
    from patchsel.pipeline import select

    kev = [t for t in instance.tasks if t.mandatory]
    unreserved_instance = Instance(instance.instance_id, instance.total_budget,
                                   [replace(t, mandatory=False) for t in instance.tasks], instance.meta)
    reserved = select(instance, "milp")
    unreserved = select(unreserved_instance, "milp")
    if reserved.proof != "optimal" or unreserved.proof != "optimal":
        raise RuntimeError(f"{instance.instance_id}: HiGHS did not prove optimality")
    reserved_score = sum(t.value for t in kev) + reserved.optional_score
    cost = unreserved.optional_score - reserved_score
    return {"instance_id": instance.instance_id, "kev_tasks": len(kev),
            "kev_kept_unreserved": len({t.task_id for t in kev} & set(unreserved.selected_ids)),
            "reserved_score": reserved_score, "unreserved_score": unreserved.optional_score,
            "score_cost": cost,
            "score_cost_pct": round(100 * cost / unreserved.optional_score, 4) if cost else 0.0}


def kev_policy_rows(pool: list[dict]) -> list[dict]:
    """kev_policy() on every main-grid instance that contains KEV tasks."""
    from patchsel.instances import generate

    rows = []
    for n in KEV_GRID["sizes"]:
        for model in COST_MODELS:
            for pct in KEV_GRID["budgets"]:
                for seed in KEV_GRID["seeds"]:
                    instance = generate(pool, n, model, pct, seed)
                    if any(t.mandatory for t in instance.tasks):
                        rows.append({"n_tasks": n, "cost_model": model, "budget_pct": pct,
                                     **kev_policy(instance)})
    return rows


def compare(out: Path, samples: int = GOOHS_SAMPLES) -> dict:
    from patchsel.prepare import load_pool

    out.mkdir(parents=True, exist_ok=True)
    rows = goohs_rows(samples)
    summary = goohs_summary(rows)
    write_csv(rows, out / "goohs_runs.csv")
    write_csv(summary, out / "goohs_summary.csv")
    figures = goohs_figure(summary, out)
    pool = load_pool()
    jacobs = jacobs_rows(pool)
    write_csv(jacobs, out / "jacobs_thresholds.csv")
    kev = kev_policy_rows(pool)
    write_csv(kev, out / "kev_policy.csv")
    return {"goohs_instances": len(rows) // 3, "goohs_summary": summary, "jacobs": jacobs,
            "kev_policy": kev, "figures": [str(p) for p in figures]}
