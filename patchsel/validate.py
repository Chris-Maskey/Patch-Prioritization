"""Independent checks of a result record against its instance."""

from __future__ import annotations

from patchsel.model import Instance, Result


def validate(instance: Instance, result: Result) -> list[str]:
    """Return a list of contract violations (empty when the result is valid)."""
    errors = []
    tasks = {t.task_id: t for t in instance.tasks}
    mandatory = {t.task_id for t in instance.tasks if t.mandatory}
    mandatory_cost = sum(tasks[i].cost for i in mandatory)
    budget = instance.total_budget

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    check(result.instance_id == instance.instance_id, "instance ID mismatch")
    check(result.total_budget == budget, "total budget mismatch")
    check(result.mandatory_cost == mandatory_cost, "mandatory cost mismatch")
    selected, deferred = result.selected_ids, result.deferred_ids
    check(len(selected) == len(set(selected)), "duplicate selected IDs")
    check(len(deferred) == len(set(deferred)), "duplicate deferred IDs")
    check(not set(selected) & set(deferred), "an ID is both selected and deferred")
    check(set(selected) | set(deferred) == set(tasks), "selected and deferred IDs do not cover the backlog")
    check(all(i in tasks for i in selected + deferred), "unknown task ID")

    if result.status == "infeasible":
        check(mandatory_cost > budget, "infeasible reported but mandatory work fits")
        check(not result.feasible, "infeasible result marked feasible")
        check(result.shortfall == mandatory_cost - budget, "wrong shortfall")
        check(not selected, "infeasible result has a selection")
        return errors

    check(mandatory_cost <= budget, "mandatory work exceeds budget but result is not infeasible")
    check(result.feasible and result.shortfall == 0, "feasible result has feasibility flags wrong")
    if result.status != "completed" and not selected:
        return errors  # a cutoff with no recoverable selection

    known = [tasks[i] for i in selected if i in tasks]
    chosen_optional = [t for t in known if not t.mandatory]
    check(mandatory <= set(selected), "mandatory task missing from selection")
    check(result.mandatory_included == (mandatory <= set(selected)), "wrong mandatory flag")
    check(result.optional_budget == budget - mandatory_cost, "wrong optional budget")
    check(result.optional_cost == sum(t.cost for t in chosen_optional), "optional cost does not match selection")
    check(result.optional_score == sum(t.value for t in chosen_optional), "optional score does not match selection")
    selected_cost = sum(t.cost for t in known)
    check(result.total_cost == selected_cost, "total cost does not match selection")
    check(selected_cost <= budget, "selection exceeds the total budget")
    return errors
