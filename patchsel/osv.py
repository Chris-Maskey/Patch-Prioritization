"""OSV record rules shared by the data audit and the dataset preparation step."""

from cvss import CVSS3
from cvss.exceptions import CVSS3Error


def alias_groups(records):
    """Link records transitively through OSV IDs and aliases, including bridges."""
    parents = {}

    def root(identifier):
        parents.setdefault(identifier, identifier)
        while parents[identifier] != identifier:
            parents[identifier] = parents[parents[identifier]]
            identifier = parents[identifier]
        return identifier

    for record in records:
        for alias in record.get("aliases", []):
            left, right = root(record["id"]), root(alias)
            parents[right] = left
    return {record["id"]: root(record["id"]) for record in records}


def eligible_scores(record):
    """Return (status, scores in tenths) for one OSV record."""
    severity = record.get("severity", []) + [
        item
        for affected in record.get("affected", [])
        for item in affected.get("severity", [])
    ]
    vectors = sorted({
        item["score"] for item in severity
        if item.get("score", "").startswith("CVSS:3.1/")
    })
    if not vectors:
        return "no_cvss31", []
    try:
        scores = [round(CVSS3(vector).scores()[0] * 10) for vector in vectors]
    except CVSS3Error:
        return "invalid_cvss31", []
    fixed = any(
        event.get("fixed")
        for affected in record.get("affected", [])
        for version_range in affected.get("ranges", [])
        for event in version_range.get("events", [])
    )
    return ("eligible", scores) if fixed else ("no_fixed_event", [])
