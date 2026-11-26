"""Data contract: tasks, instances, and result records (see "Data contract" in README.md)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path

INSTANCE_SCHEMA = "cp600.instance/v1"
RESULT_SCHEMA = "cp600.result/v1"


@dataclass(frozen=True, slots=True)
class Task:
    """One patching task: a consistent OSV alias group with a simulated cost."""

    task_id: str
    value: int  # CVSS 3.1 base score in tenths, 0..100
    cost: int  # simulated effort in primary time units (30 minutes)
    mandatory: bool  # KEV-matched under the experimental policy
    kev_status: str = "no_cve"  # match | no_match | no_cve

    def __post_init__(self):
        if not 0 <= self.value <= 100:
            raise ValueError(f"{self.task_id}: value {self.value} outside 0..100")
        if self.cost < 1:
            raise ValueError(f"{self.task_id}: cost must be a positive integer")


@dataclass(slots=True)
class Instance:
    instance_id: str
    total_budget: int  # W, in primary time units
    tasks: list[Task]
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        ids = [task.task_id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.instance_id}: duplicate task IDs")
        if self.total_budget < 0:
            raise ValueError(f"{self.instance_id}: negative total budget")

    def to_dict(self) -> dict:
        return {
            "schema": INSTANCE_SCHEMA,
            "instance_id": self.instance_id,
            "total_budget": self.total_budget,
            "meta": self.meta,
            "task_fields": ["task_id", "value", "cost", "mandatory", "kev_status"],
            "tasks": [[t.task_id, t.value, t.cost, t.mandatory, t.kev_status] for t in self.tasks],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Instance:
        if data.get("schema") != INSTANCE_SCHEMA:
            raise ValueError(f"unsupported instance schema: {data.get('schema')!r}")
        fields = data["task_fields"]
        tasks = [Task(**dict(zip(fields, row))) for row in data["tasks"]]
        return cls(data["instance_id"], data["total_budget"], tasks, data.get("meta", {}))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), separators=(",", ":")) + "\n")

    @classmethod
    def load(cls, path: Path) -> Instance:
        return cls.from_dict(json.loads(Path(path).read_text()))


@dataclass(slots=True)
class Result:
    """One method's selection on one instance."""

    instance_id: str
    method: str
    status: str  # completed | infeasible | timeout | memory_limit | error
    feasible: bool  # False only when mandatory cost exceeds the total budget
    proof: str  # optimal | heuristic | unproven | none
    total_budget: int
    mandatory_cost: int
    shortfall: int
    optional_budget: int
    n_tasks: int
    n_mandatory: int
    n_optional: int
    n_solver: int  # optional tasks left after common preprocessing
    value_sum: int  # P: total value of the solver's input tasks
    selected_ids: list[str]
    deferred_ids: list[str]
    optional_score: int
    optional_cost: int
    total_cost: int
    mandatory_included: bool
    runtime_ns: int
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"schema": RESULT_SCHEMA, **asdict(self)}
