"""Depth-first branch and bound with a fractional-knapsack upper bound."""

from __future__ import annotations

from time import perf_counter
from typing import Sequence

from patchsel.model import Task
from patchsel.solvers.base import Solution
from patchsel.solvers.greedy import ratio_greedy, ratio_order

CHECK_EVERY = 256  # nodes between time-limit checks


def fractional_bound(values: Sequence[int], costs: Sequence[int], k: int, capacity: int) -> int:
    """Upper bound on the best score from items k.. (sorted by ratio) within capacity.

    Fill whole items in ratio order, then a fraction of the first that does not
    fit. Integer scores make the floor of this bound still valid.
    """
    bound = 0
    for j in range(k, len(values)):
        if costs[j] <= capacity:
            capacity -= costs[j]
            bound += values[j]
        else:
            return bound + values[j] * capacity // costs[j]
    return bound


def branch_and_bound(items: Sequence[Task], budget: int, time_limit: float | None = None) -> Solution:
    """Include-first DFS over items in ratio order.

    The incumbent starts as the benefit-per-cost greedy selection. A node is
    pruned when its bound cannot beat the incumbent. With ``time_limit`` (seconds),
    the search stops and returns the incumbent with optimality unproven.
    """
    order = ratio_order(items)
    values = [items[i].value for i in order]
    costs = [items[i].cost for i in order]
    n = len(order)

    greedy = ratio_greedy(items, budget).chosen
    greedy_score = best_score = sum(items[i].value for i in greedy)
    best_link, improved = None, False
    deadline = None if time_limit is None else perf_counter() + time_limit

    # A node is (position, score, cost, link); link is a shared linked list of
    # included positions, so the open nodes need O(n) memory in total.
    stack = [(0, 0, 0, None)]
    nodes = pruned = 0
    cutoff = False
    while stack:
        if deadline is not None and nodes % CHECK_EVERY == 0 and perf_counter() >= deadline:
            cutoff = True
            break
        k, score, cost, link = stack.pop()
        nodes += 1
        if score > best_score:
            best_score, best_link, improved = score, link, True
        if k == n:
            continue
        if score + fractional_bound(values, costs, k, budget - cost) <= best_score:
            pruned += 1
            continue
        stack.append((k + 1, score, cost, link))  # exclude, explored second
        if cost + costs[k] <= budget:
            stack.append((k + 1, score + values[k], cost + costs[k], (k, link)))  # include first

    if improved:
        chosen = []
        while best_link is not None:
            position, best_link = best_link
            chosen.append(order[position])
        chosen.sort()
    else:
        chosen = sorted(greedy)
    stats = {"nodes": nodes, "pruned": pruned, "greedy_score": greedy_score, "improved_on_greedy": improved}
    if cutoff:
        return Solution(chosen, "unproven", stats, status="timeout")
    return Solution(chosen, "optimal", stats)
