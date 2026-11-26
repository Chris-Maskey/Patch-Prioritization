# /// script
# requires-python = ">=3.11"
# dependencies = ["cvss==3.6"]
# ///
"""Audit saved OSV PyPI and CISA KEV snapshots without modifying them.

Run from the project directory:
    uv run check_data.py --self-test
    uv run check_data.py
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from patchsel.osv import alias_groups, eligible_scores


DATA = Path(__file__).resolve().parent / "data"
SOURCES = {
    "pypi.zip": "https://storage.googleapis.com/osv-vulnerabilities/PyPI/all.zip",
    "kev.json": "https://raw.githubusercontent.com/cisagov/kev-data/develop/known_exploited_vulnerabilities.json",
}


def self_test():
    records = [
        {"id": "A", "aliases": ["CVE-X"]},
        {"id": "bridge", "aliases": ["CVE-X", "CVE-Y"]},
        {"id": "B", "aliases": ["CVE-Y"]},
        {"id": "separate"},
    ]
    groups = alias_groups(records)
    assert groups["A"] == groups["B"] == groups["bridge"]
    assert groups["A"] != groups["separate"]
    record = {
        "severity": [{"score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
        "affected": [{"ranges": [{"events": [{"fixed": "1.0"}]}]}],
    }
    assert eligible_scores(record) == ("eligible", [98])
    assert eligible_scores({}) == ("no_cvss31", [])
    record["affected"] = []
    assert eligible_scores(record) == ("no_fixed_event", [])
    record["severity"][0]["score"] = "CVSS:3.1/INVALID"
    assert eligible_scores(record) == ("invalid_cvss31", [])
    print("Passed: transitive aliases, separate records, CVSS scoring, and exclusions.")


def audit():
    records = []
    counts = Counter()
    with ZipFile(DATA / "raw" / "pypi.zip") as archive:
        for name in sorted(archive.namelist()):
            if name.endswith(".json"):
                record = json.loads(archive.read(name))
                counts["total_records"] += 1
                if record.get("withdrawn"):
                    counts["withdrawn_records"] += 1
                else:
                    records.append(record)
    counts["active_records"] = len(records)
    groups = alias_groups(records)
    kev = json.loads((DATA / "raw" / "kev.json").read_text())
    kev_ids = {entry["cveID"] for entry in kev["vulnerabilities"]}
    group_ids, group_scores = {}, {}
    for record in records:
        group = groups[record["id"]]
        group_ids.setdefault(group, set()).update([record["id"], *record.get("aliases", [])])
        status, scores = eligible_scores(record)
        counts[status + "_records"] += 1
        if scores:
            group_scores.setdefault(group, set()).update(scores)
    matched_cves = set()
    for group in group_scores:
        hits = group_ids[group] & kev_ids
        matched_cves.update(hits)
        counts["eligible_kev_groups"] += bool(hits)
    counts["eligible_unique_groups"] = len(group_scores)
    counts["eligible_groups_with_score_disagreement"] = sum(
        len(scores) > 1 for scores in group_scores.values()
    )
    counts["eligible_distinct_kev_cves"] = len(matched_cves)
    consistent_groups = {group for group, scores in group_scores.items() if len(scores) == 1}
    counts["consistent_unique_groups"] = len(consistent_groups)
    counts["consistent_kev_groups"] = sum(
        bool(group_ids[group] & kev_ids) for group in consistent_groups
    )
    assert counts["total_records"] == len(records) + counts["withdrawn_records"]
    assert len(records) == sum(counts[key + "_records"] for key in
                               ["eligible", "no_cvss31", "invalid_cvss31", "no_fixed_event"])
    report = {
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "ecosystem": "PyPI",
        "cvss_version": "3.1",
        "cvss_library": "cvss==3.6",
        "initial_dataset_rule": "Exclude alias groups with conflicting eligible CVSS 3.1 base scores.",
        "kev_catalog_version": kev["catalogVersion"],
        "kev_catalog_released": kev["dateReleased"],
        "counts": dict(sorted(counts.items())),
        "matched_kev_cves": sorted(matched_cves),
        "sources": {
            name: {"url": url, "bytes": (DATA / "raw" / name).stat().st_size,
                   "sha256": sha256((DATA / "raw" / name).read_bytes()).hexdigest()}
            for name, url in SOURCES.items()
        },
        "limits": [
            "A fixed-version event is a metadata filter, not a verified deployment plan.",
            "Alias groups model independent vulnerability tasks, not package upgrades.",
            "Groups with CVSS disagreements are counted but excluded from the initial dataset.",
            "Applicability and remediation costs remain simulated; no real systems were scanned.",
        ],
    }
    output = DATA / "feasibility.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        audit()
