"""Benchmark runner: one isolated worker process per run, executed one at a time.

The parent generates instances, starts each worker, enforces the limits, and
appends one JSON line per run as soon as the run ends. A rerun with the same
output file skips runs that are already recorded.

Limits:
- Time: the worker measures selection time (pipeline.select). Branch and bound
  stops itself at the limit and returns its incumbent. Other methods that finish
  over the limit are marked ``timeout``. The parent kills a worker that is still
  running at limit + STARTUP_GRACE seconds.
- Memory: the parent polls the worker's resident set size and kills it when it
  exceeds the limit. Peak RSS comes from the kernel's rusage for the worker.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import time

from patchsel.model import Instance
from patchsel.pipeline import select
from patchsel.validate import validate

ROOT = Path(__file__).resolve().parent.parent
STARTUP_GRACE = 3.0  # seconds for interpreter start and instance load
POLL_SECONDS = 0.05
TIME_LIMITED = {"bnb", "milp"}  # methods that stop themselves at the limit


def worker(instance_path: str, method: str, time_limit: str) -> None:
    """Child process: run one method and print the result record as JSON."""
    instance = Instance.load(Path(instance_path))
    if method == "milp":
        import scipy.optimize  # noqa: F401  load before the timer starts
    options = {"time_limit": float(time_limit)} if method in TIME_LIMITED else {}
    print(json.dumps(select(instance, method, **options).to_dict()))


def _rss_bytes(pid: int) -> int:
    output = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout
    return int(output.strip() or 0) * 1024


def _peak_bytes(rusage) -> int:
    return rusage.ru_maxrss if sys.platform == "darwin" else rusage.ru_maxrss * 1024


def run_once(instance: Instance, path: Path, method: str, time_limit: float, memory_limit: int) -> dict:
    """Run one worker and return its row, without the run key fields."""
    # Files, not pipes: a large result would fill a pipe buffer and block the worker.
    with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
        process = subprocess.Popen(
            [sys.executable, "-m", "patchsel.runner", str(path), method, str(time_limit)],
            cwd=ROOT, stdout=out, stderr=err, text=True,
        )
        killed, status, rusage = _supervise(process, time_limit, memory_limit)
        out.seek(0)
        err.seek(0)
        stdout, stderr = out.read(), err.read()
    exit_code = os.waitstatus_to_exitcode(status)
    return _row(instance, killed, exit_code, _peak_bytes(rusage), stdout, stderr, time_limit, memory_limit)


def _supervise(process: subprocess.Popen, time_limit: float, memory_limit: int):
    """Wait for the worker; kill it at the time or memory limit."""
    deadline = time.monotonic() + time_limit + STARTUP_GRACE
    killed = None
    while True:
        pid, status, rusage = os.wait4(process.pid, os.WNOHANG)
        if pid:
            break
        if time.monotonic() > deadline:
            killed = "timeout"
        elif _rss_bytes(process.pid) > memory_limit:
            killed = "memory_limit"
        if killed:
            process.send_signal(signal.SIGKILL)
            _, status, rusage = os.wait4(process.pid, 0)
            break
        time.sleep(POLL_SECONDS)
    process.returncode = os.waitstatus_to_exitcode(status)
    return killed, status, rusage


def _row(instance, killed, exit_code, peak, stdout, stderr, time_limit, memory_limit) -> dict:
    row = {"peak_rss_bytes": peak, "exit_code": exit_code}
    if killed:
        return {**row, "status": killed, "proof": "none", "selection": False}
    if exit_code != 0 or not stdout.strip():
        message = (stderr.strip().splitlines() or ["no output"])[-1]
        return {**row, "status": "error", "proof": "none", "selection": False, "error": message}

    result = json.loads(stdout.strip().splitlines()[-1])
    if result["status"] == "completed" and result["runtime_ns"] > time_limit * 1e9:
        result["status"] = "timeout"  # finished, but over the selection-time limit
    if row["peak_rss_bytes"] > memory_limit:
        result["status"] = "memory_limit"
    errors = validate(instance, _as_result(result))
    return {**row, **result, "selection": True, "valid": not errors, "validation_errors": errors}


def _as_result(record: dict):
    from patchsel.model import Result

    fields = {k: v for k, v in record.items() if k != "schema"}
    return Result(**fields)


def environment(time_limit: float, memory_limit: int) -> dict:
    cpu = platform.processor()
    if sys.platform == "darwin":
        cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                             capture_output=True, text=True).stdout.strip() or cpu
    return {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "os": platform.platform(),
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "time_limit_s": time_limit,
        "memory_limit_bytes": memory_limit,
        "startup_grace_s": STARTUP_GRACE,
    }


def run_grid(instances: list[tuple[Instance, Path]], methods: list[str], out: Path, *,
             repeats: int, time_limit: float, memory_limit: int, log=print) -> None:
    """Run each (instance, method) once; repeat only runs that completed."""
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {}  # recorded run key -> status
    if out.exists():
        for line in out.read_text().splitlines():
            row = json.loads(line)
            done[row["instance_id"], row["method"], row["repeat"]] = row["status"]
    env_path = out.with_suffix(".env.json")
    if not env_path.exists():
        env_path.write_text(json.dumps(environment(time_limit, memory_limit), indent=2) + "\n")

    total = len(instances) * len(methods)
    for count, ((instance, path), method) in enumerate(
            ((pair, m) for pair in instances for m in methods), start=1):
        for repeat in range(repeats):
            key = (instance.instance_id, method, repeat)
            if key in done:
                if done[key] != "completed":
                    break  # recorded as limit-stopped or failed
                continue
            row = {"instance_id": instance.instance_id, "method": method, "repeat": repeat,
                   "time_limit_s": time_limit, "memory_limit_bytes": memory_limit,
                   **instance.meta,
                   **run_once(instance, path, method, time_limit, memory_limit)}
            with out.open("a") as handle:
                handle.write(json.dumps(row) + "\n")
            ms = row.get("runtime_ns", 0) / 1e6
            log(f"[{count}/{total}] {instance.instance_id} {method:<9} r{repeat} {row['status']:<12} "
                f"score={row.get('optional_score', '-')} {ms:.1f} ms "
                f"rss={row['peak_rss_bytes'] / 2**20:.0f} MiB")
            if row["status"] != "completed":
                break  # limit-stopped or failed runs run once


if __name__ == "__main__":
    worker(*sys.argv[1:])
