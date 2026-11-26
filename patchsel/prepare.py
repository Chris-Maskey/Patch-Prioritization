"""Build the prepared evaluation pool from the saved OSV and KEV snapshots."""

from __future__ import annotations

from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from patchsel.osv import alias_groups, eligible_scores

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
POOL = DATA / "prepared" / "pool.csv"
POOL_META = DATA / "prepared" / "pool_meta.json"
POOL_FIELDS = ["group_id", "value", "kev_status", "cve_ids", "osv_ids"]


def file_sha256(path: Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def build_pool(data: Path = DATA) -> tuple[list[dict], dict]:
    """Apply the audit rules and return (pool rows sorted by group_id, summary)."""
    audit = json.loads((data / "feasibility.json").read_text())
    for name, source in audit["sources"].items():
        actual = file_sha256(data / "raw" / name)
        if actual != source["sha256"]:
            raise RuntimeError(f"{name}: SHA-256 {actual} does not match the audited snapshot")

    records = []
    with ZipFile(data / "raw" / "pypi.zip") as archive:
        for name in sorted(archive.namelist()):
            if name.endswith(".json"):
                record = json.loads(archive.read(name))
                if not record.get("withdrawn"):
                    records.append(record)
    kev = json.loads((data / "raw" / "kev.json").read_text())
    kev_ids = {entry["cveID"] for entry in kev["vulnerabilities"]}

    groups = alias_groups(records)
    members, identifiers, scores = {}, {}, {}
    for record in records:
        group = groups[record["id"]]
        members.setdefault(group, set()).add(record["id"])
        identifiers.setdefault(group, set()).update([record["id"], *record.get("aliases", [])])
        _, record_scores = eligible_scores(record)
        if record_scores:
            scores.setdefault(group, set()).update(record_scores)

    rows = []
    for group, group_scores in scores.items():
        if len(group_scores) != 1:
            continue  # conflicting eligible scores: excluded by the audit rule
        cves = sorted(i for i in identifiers[group] if i.startswith("CVE-"))
        kev_status = "match" if set(cves) & kev_ids else ("no_match" if cves else "no_cve")
        rows.append({
            "group_id": min(members[group]),
            "value": next(iter(group_scores)),
            "kev_status": kev_status,
            "cve_ids": ";".join(cves),
            "osv_ids": ";".join(sorted(members[group])),
        })
    rows.sort(key=lambda row: row["group_id"])

    expected = audit["counts"]
    kev_rows = sum(row["kev_status"] == "match" for row in rows)
    if len(rows) != expected["consistent_unique_groups"] or kev_rows != expected["consistent_kev_groups"]:
        raise RuntimeError(f"pool has {len(rows)} rows / {kev_rows} KEV; audit expects "
                           f"{expected['consistent_unique_groups']} / {expected['consistent_kev_groups']}")
    if len({row["group_id"] for row in rows}) != len(rows):
        raise RuntimeError("group IDs are not unique")

    summary = {
        "rows": len(rows),
        "kev_status": dict(sorted(Counter(row["kev_status"] for row in rows).items())),
        "zero_value_rows": sum(row["value"] == 0 for row in rows),
        "value_min": min(row["value"] for row in rows),
        "value_max": max(row["value"] for row in rows),
        "kev_catalog_version": audit["kev_catalog_version"],
        "cvss_library": audit["cvss_library"],
        "sources": audit["sources"],
        "rules": [
            "Exclude withdrawn OSV records.",
            "Merge records transitively through IDs and aliases.",
            "A record is eligible with a valid CVSS 3.1 vector and a fixed-version event.",
            "Keep groups whose eligible records share one base score; value = score x 10.",
            "group_id is the smallest OSV record ID in the group.",
            "kev_status: match (a CVE alias is in KEV), no_match (CVEs present, none in KEV), "
            "no_cve (no CVE identifier, so KEV membership cannot be checked).",
        ],
    }
    return rows, summary


def write_pool(rows: list[dict], summary: dict, pool: Path = POOL, meta: Path = POOL_META) -> dict:
    pool.parent.mkdir(parents=True, exist_ok=True)
    with pool.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POOL_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = {"file": pool.name, "sha256": file_sha256(pool), **summary}
    meta.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def load_pool(pool: Path = POOL) -> list[dict]:
    with Path(pool).open(newline="") as handle:
        return [{**row, "value": int(row["value"])} for row in csv.DictReader(handle)]
