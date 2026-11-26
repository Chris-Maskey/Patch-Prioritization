"""Summaries and report figures from benchmark rows (task 12)."""

from __future__ import annotations

from collections import defaultdict
import csv
import json
import math
from pathlib import Path
from statistics import median

METHODS = ["severity", "ratio", "dp_budget", "dp_value", "bnb", "milp"]
LABELS = {"severity": "Severity-first greedy", "ratio": "Benefit-per-cost greedy",
          "dp_budget": "Budget-based DP", "dp_value": "Value-based DP", "bnb": "Branch and bound",
          "milp": "Integer programming (HiGHS)"}
COST_MODELS = ["equal", "uniform", "correlated"]
COST_LABELS = {"equal": "Equal costs", "uniform": "Uniform costs 1-20", "correlated": "Severity-correlated costs"}

# Validated categorical slots 1-6 (light surface), fixed order per method.
COLORS = dict(zip(METHODS, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]))
MARKERS = dict(zip(METHODS, ["o", "s", "^", "D", "v", "P"]))
BUDGET_COLORS = {10: "#86b6ef", 30: "#2a78d6", 50: "#104281"}  # ordinal blue ramp
SURFACE, GRID, INK, MUTED = "#fcfcfb", "#e4e3df", "#0b0b0b", "#52514e"


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def runs(rows: list[dict]) -> dict:
    """(instance_id, method) -> one record: first-repeat outcome plus median completed time."""
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["instance_id"], row["method"]].append(row)
    merged = {}
    for key, group in grouped.items():
        group.sort(key=lambda r: r["repeat"])
        first = dict(group[0])
        times = [r["runtime_ns"] for r in group if r["status"] == "completed"]
        first["runtime_ms_median"] = median(times) / 1e6 if times else None
        first["runtime_ms_range"] = (min(times) / 1e6, max(times) / 1e6) if times else None
        first["repeats"] = len(group)
        merged[key] = first
    return merged


def optima(merged: dict) -> dict:
    """instance_id -> proven optimal optional score; raises if exact methods disagree."""
    best = {}
    for (instance, method), row in merged.items():
        if row.get("proof") == "optimal":
            if instance in best and best[instance] != row["optional_score"]:
                raise RuntimeError(f"{instance}: certified scores disagree ({best[instance]} vs "
                                   f"{row['optional_score']} from {method})")
            best[instance] = row["optional_score"]
    return best


def gap(row: dict, opt: int | None) -> float | None:
    """Percent gap to a proven optimum (absolute difference when the optimum is 0)."""
    if opt is None or not row.get("selection"):
        return None
    if opt == 0:
        return float(opt - row["optional_score"])
    return 100 * (opt - row["optional_score"]) / opt


def reconcile(rows: list[dict], merged: dict) -> dict:
    instances = {r["instance_id"] for r in rows}
    methods = [m for m in METHODS if any(r["method"] == m for r in rows)]
    missing = [(i, m) for i in sorted(instances) for m in methods if (i, m) not in merged]
    short = [k for k, r in merged.items() if r["status"] == "completed" and r["repeats"] < 3]
    invalid = [k for k, r in merged.items() if r.get("selection") and not r.get("valid")]
    return {"rows": len(rows), "instances": len(instances), "runs": len(merged),
            "missing_runs": missing, "completed_with_fewer_than_3_repeats": short,
            "invalid_selections": invalid}


def repeat_spread(rows: list[dict]) -> dict:
    """Range of the three repeats of each completed run, as a percent of its median time."""
    times = defaultdict(list)
    for row in rows:
        if row["status"] == "completed":
            times[row["instance_id"], row["method"]].append(row["runtime_ns"])

    def describe(spreads: list[float]) -> dict:
        spreads = sorted(spreads)
        return {"runs": len(spreads), "median": _round(median(spreads)),
                "p90": _round(spreads[int(0.9 * len(spreads))]), "max": _round(spreads[-1])}

    full = [t for t in times.values() if len(t) == 3]
    spread = [100 * (max(t) - min(t)) / median(t) for t in full]
    long = [100 * (max(t) - min(t)) / median(t) for t in full if median(t) >= 100e6]
    return {"all_completed_runs": describe(spread), "runs_of_at_least_100_ms": describe(long)}


def summary_table(merged: dict, best: dict) -> list[dict]:
    cells = defaultdict(list)
    for (instance, method), row in merged.items():
        cells[row["n_tasks"], row["cost_model"], row["budget_pct"], method].append(row)
    table = []
    for (n, model, pct, method), group in sorted(cells.items(), key=lambda kv: (
            kv[0][0], COST_MODELS.index(kv[0][1]), kv[0][2], METHODS.index(kv[0][3]))):
        status = defaultdict(int)
        for row in group:
            status[row["status"]] += 1
        gaps = [g for row in group if (g := gap(row, best.get(row["instance_id"]))) is not None]
        times = [row["runtime_ms_median"] for row in group if row["runtime_ms_median"] is not None]
        rss = [row["peak_rss_bytes"] / 2**20 for row in group if row["status"] == "completed"]
        nodes = [row["stats"]["nodes"] for row in group if method == "bnb" and row.get("stats")]
        table.append({
            "n_tasks": n, "cost_model": model, "budget_pct": pct, "method": method,
            "instances": len(group), "completed": status["completed"], "timeout": status["timeout"],
            "memory_limit": status["memory_limit"], "error": status["error"],
            "proven_optimum": sum(row["instance_id"] in best for row in group),
            "gap_pct_median": _round(median(gaps)) if gaps else "",
            "gap_pct_max": _round(max(gaps)) if gaps else "",
            "runtime_ms_median": _round(median(times)) if times else "",
            "runtime_ms_max": _round(max(times)) if times else "",
            "peak_rss_mib_median": _round(median(rss)) if rss else "",
            "bnb_nodes_median": median(nodes) if nodes else "",
        })
    return table


def paired_table(merged: dict, best: dict) -> list[dict]:
    """Win/tie/loss counts on the same instance, by cost model and in total."""
    pairs = [("ratio", "severity"), ("optimum", "ratio"), ("optimum", "severity")]
    instances = defaultdict(dict)
    for (instance, method), row in merged.items():
        if row.get("selection"):
            instances[instance][method] = row["optional_score"]
            instances[instance]["cost_model"] = row["cost_model"]
    for instance, scores in instances.items():
        if instance in best:
            scores["optimum"] = best[instance]
    table = []
    for model in [*COST_MODELS, "all"]:
        for a, b in pairs:
            wins = ties = losses = 0
            for scores in instances.values():
                if model != "all" and scores["cost_model"] != model or a not in scores or b not in scores:
                    continue
                wins += scores[a] > scores[b]
                ties += scores[a] == scores[b]
                losses += scores[a] < scores[b]
            table.append({"cost_model": model, "comparison": f"{a} vs {b}",
                          "higher": wins, "equal": ties, "lower": losses})
    return table


def loglog_slope(points: list[tuple[float, float]]) -> float:
    """Least-squares slope of log(y) against log(x): the empirical growth exponent."""
    xs = [math.log(x) for x, _ in points]
    ys = [math.log(y) for _, y in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)


def growth_table(summary: list[dict], pct: int = 30, min_n: int = 250) -> list[dict]:
    """Growth exponent of median time in N, per method and cost model, at one budget share.

    Uses sizes N >= min_n (small sizes are dominated by fixed overhead) whose runs all completed.
    B and P both grow in proportion to N, so O(nB) and O(nP) predict an exponent of 2.
    """
    table = []
    for method in METHODS:
        for model in COST_MODELS:
            points = [(r["n_tasks"], r["runtime_ms_median"]) for r in summary
                      if r["method"] == method and r["cost_model"] == model and r["budget_pct"] == pct
                      and r["n_tasks"] >= min_n and r["completed"] == r["instances"]]
            if len(points) >= 3:
                table.append({"method": method, "cost_model": model, "budget_pct": pct,
                              "sizes": " ".join(str(n) for n, _ in points),
                              "exponent": round(loglog_slope(points), 2)})
    return table


def _round(value: float) -> float:
    return round(value, 4)


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def units_table(rows: list[dict]) -> list[dict]:
    """Task 11: compare representations of the same base instance."""
    merged = runs(rows)
    table, mismatches = [], []
    by_base = defaultdict(dict)
    for (instance, method), row in merged.items():
        by_base[row.get("base_instance", instance), method][row.get("representation", "original")] = row
    for (base, method), variants in sorted(by_base.items()):
        certified = {r["optional_score"] for r in variants.values() if r.get("proof") == "optimal"}
        if len(certified) > 1:
            mismatches.append((base, method))
        for name in ("original", "x6", "gcd"):
            row = variants.get(name)
            if row is None:
                continue
            table.append({
                "base_instance": base, "method": method, "representation": name,
                "cost_divisor": row.get("cost_divisor", ""), "optional_budget": row["optional_budget"],
                "value_sum": row.get("value_sum", ""), "status": row["status"], "proof": row["proof"],
                "optional_score": row.get("optional_score", ""),
                "table_cells": (row.get("stats") or {}).get("table_cells", ""),
                "bnb_nodes": (row.get("stats") or {}).get("nodes", ""),
                "runtime_ms_median": _round(row["runtime_ms_median"]) if row["runtime_ms_median"] else "",
            })
    if mismatches:
        raise RuntimeError(f"certified scores differ across representations: {mismatches}")
    return table


# ---------------------------------------------------------------- figures

def _style():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.linewidth": 0.8, "axes.grid": True, "grid.color": GRID,
        "grid.linewidth": 0.8, "grid.linestyle": "-", "axes.axisbelow": True,
        "axes.spines.top": False, "axes.spines.right": False,
        "text.color": INK, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.titlesize": 10, "axes.labelsize": 9, "xtick.labelsize": 8, "ytick.labelsize": 8,
        "legend.fontsize": 8, "legend.frameon": False, "font.family": "DejaVu Sans",
        "lines.linewidth": 2, "lines.solid_capstyle": "round", "lines.solid_joinstyle": "round",
    })
    return plt


def _line(ax, xs, ys, method=None, color=None, label=None, marker=None):
    ax.plot(xs, ys, color=color or COLORS[method], marker=marker or MARKERS[method], markersize=6,
            markeredgecolor=SURFACE, markeredgewidth=1.5, label=label or LABELS[method])


def _size_axis(ax, sizes):
    ax.set_xscale("log")
    ax.set_xticks(sizes)
    ax.set_xticklabels([f"{n:,}" for n in sizes], rotation=45)
    ax.minorticks_off()


def _save(fig, out: Path, name: str) -> list[Path]:
    paths = [out / f"{name}.pdf", out / f"{name}.png"]
    for path in paths:
        fig.savefig(path, dpi=200, bbox_inches="tight")
    return paths


def figures(merged: dict, best: dict, out: Path) -> list[Path]:
    plt = _style()
    sizes = sorted({r["n_tasks"] for r in merged.values()})
    written = []

    def cell(model, method, pct=None):
        return [r for r in merged.values() if r["cost_model"] == model and r["method"] == method
                and (pct is None or r["budget_pct"] == pct)]

    # Figures are drawn at the report's text width (6.5 in), so font sizes print as set.
    # 1. Greedy loss: severity % gap; ratio absolute gap against the proven bound of 100.
    #    Line: median over seeds; band: min to max.
    fig, axes = plt.subplots(2, 3, figsize=(6.5, 3.9), sharex=True, sharey="row")
    for col, model in enumerate(COST_MODELS):
        for pct, color in BUDGET_COLORS.items():
            for row_index, method in enumerate(["severity", "ratio"]):
                xs, ys, lows, highs = [], [], [], []
                for n in sizes:
                    values = []
                    for r in cell(model, method, pct):
                        opt = best.get(r["instance_id"])
                        if r["n_tasks"] == n and opt is not None:
                            values.append(gap(r, opt) if method == "severity" else opt - r["optional_score"])
                    if values:
                        xs.append(n)
                        ys.append(median(values))
                        lows.append(min(values))
                        highs.append(max(values))
                axes[row_index][col].fill_between(xs, lows, highs, color=color, alpha=0.15, linewidth=0)
                _line(axes[row_index][col], xs, ys, color=color, marker="o", label=f"{pct}% budget")
        axes[0][col].set_title(COST_LABELS[model])
        axes[1][col].axhline(100, color=MUTED, linewidth=1)
        axes[1][col].text(sizes[0], 100, " proven bound: 100", va="bottom", fontsize=7, color=MUTED)
        _size_axis(axes[1][col], sizes)
        axes[1][col].set_xlabel("Backlog size N")
    axes[0][0].set_ylabel("Severity-first\ngap (% of optimum)")
    axes[1][0].set_ylabel("Benefit-per-cost gap\n(score tenths)")
    axes[0][2].legend(loc="upper right")
    fig.tight_layout()
    written += _save(fig, out, "fig1_greedy_gap")
    plt.close(fig)

    # 2. Runtime, 30% budget. A point is drawn only where every instance completed, so a
    #    median never comes from the few runs that finished; gaps (NaN) break the line.
    fig, axes = plt.subplots(1, 3, figsize=(6.5, 2.7), sharey=True)
    for col, model in enumerate(COST_MODELS):
        ax = axes[col]
        for method in [m for m in METHODS if any(r["method"] == m for r in merged.values())]:
            ys = []
            for n in sizes:
                group = [r for r in cell(model, method, 30) if r["n_tasks"] == n]
                complete = group and all(r["status"] == "completed" for r in group)
                ys.append(median(r["runtime_ms_median"] for r in group) if complete else math.nan)
            _line(ax, sizes, ys, method)
        ax.axhline(10_000, color=MUTED, linewidth=1)
        ax.text(sizes[0], 10_000, " 10 s limit", va="bottom", fontsize=7, color=MUTED)
        ax.set_yscale("log")
        ax.set_title(COST_LABELS[model])
        _size_axis(ax, sizes)
        ax.set_xlabel("Backlog size N")
    axes[0].set_ylabel("Selection time, ms (log)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3)
    fig.tight_layout(rect=(0, 0.15, 1, 1))
    written += _save(fig, out, "fig2_runtime")
    plt.close(fig)

    # 3. Completion rate, all budgets. Methods that completed every run are not drawn, because
    # their lines at 100% would hide each other; the figure caption names them.
    present = [m for m in METHODS if any(r["method"] == m for r in merged.values())]
    always = [m for m in present
              if all(r["status"] == "completed" for r in merged.values() if r["method"] == m)]
    fig, axes = plt.subplots(1, 3, figsize=(6.5, 2.4), sharey=True)
    for col, model in enumerate(COST_MODELS):
        ax = axes[col]
        for method in [m for m in present if m not in always]:
            ys = []
            for n in sizes:
                group = [r for r in cell(model, method) if r["n_tasks"] == n]
                ys.append(100 * sum(r["status"] == "completed" for r in group) / len(group))
            _line(ax, sizes, ys, method)
        ax.set_ylim(-5, 105)
        ax.set_title(COST_LABELS[model])
        _size_axis(ax, sizes)
        ax.set_xlabel("Backlog size N")
    axes[0].set_ylabel("Completed runs (%)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2)
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    written += _save(fig, out, "fig3_completion")
    plt.close(fig)

    # 4. Peak memory of completed runs, 30% budget.
    fig, axes = plt.subplots(1, 3, figsize=(6.5, 2.6), sharey=True)
    for col, model in enumerate(COST_MODELS):
        ax = axes[col]
        for method in [m for m in METHODS if any(r["method"] == m for r in merged.values())]:
            xs, ys = [], []
            for n in sizes:
                rss = [r["peak_rss_bytes"] / 2**20 for r in cell(model, method, 30)
                       if r["n_tasks"] == n and r["status"] == "completed"]
                if rss:
                    xs.append(n)
                    ys.append(median(rss))
            _line(ax, xs, ys, method)
        ax.set_title(COST_LABELS[model])
        _size_axis(ax, sizes)
        ax.set_xlabel("Backlog size N")
    axes[0].set_ylabel("Peak worker RSS (MiB)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3)
    fig.tight_layout(rect=(0, 0.15, 1, 1))
    written += _save(fig, out, "fig4_memory")
    plt.close(fig)

    # 5. DP time against DP work (inner-loop updates), all completed DP runs.
    fig, ax = plt.subplots(figsize=(5.2, 3.8))
    for method in ["dp_budget", "dp_value"]:
        points = [(r["stats"]["updates"], r["runtime_ms_median"]) for r in merged.values()
                  if r["method"] == method and r["status"] == "completed" and r["stats"].get("updates")]
        ax.scatter([p[0] for p in points], [p[1] for p in points], s=22, color=COLORS[method],
                   marker=MARKERS[method], edgecolors=SURFACE, linewidths=1, label=LABELS[method])
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("DP table updates (about nB or nP/2)")
    ax.set_ylabel("Selection time, ms")
    ax.legend(loc="upper left")
    ax.set_title("DP time follows table work, not backlog size", fontsize=10)
    fig.tight_layout()
    written += _save(fig, out, "fig5_dp_work")
    plt.close(fig)
    return written


def analyze(results: Path, out: Path, units: Path | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rows = load(results)
    merged = runs(rows)
    best = optima(merged)
    report = reconcile(rows, merged)
    report["instances_with_proven_optimum"] = len(best)
    report["repeat_spread_pct"] = repeat_spread(rows)
    summary = summary_table(merged, best)
    write_csv(summary, out / "summary.csv")
    write_csv(growth_table(summary), out / "growth.csv")
    write_csv(paired_table(merged, best), out / "paired.csv")
    report["figures"] = [str(p) for p in figures(merged, best, out)]
    if units:
        write_csv(units_table(load(units)), out / "units.csv")
    (out / "reconcile.json").write_text(json.dumps(report, indent=2, default=list) + "\n")
    return report
