"""Enforce the plan §20.1 per-module 100% coverage gate."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REQUIRED_FULL_COVERAGE = (
    "backend/app/core/security.py",
    "backend/app/services/gmail/parser.py",
    "backend/app/services/ingestion/dedup.py",
    "backend/app/llm/client.py",
    "backend/app/services/jobs/predicate.py",
)


def _line_rate(root: ET.Element, target: str) -> float | None:
    """Return the coverage.py XML line-rate for ``target``."""
    target_path = Path(target)
    suffixes = (
        target,
        target.removeprefix("backend/"),
        target.removeprefix("backend/app/"),
    )
    for class_el in root.findall(".//class"):
        filename = class_el.get("filename")
        if filename is None:
            continue
        candidate = Path(filename)
        candidate_text = candidate.as_posix()
        if candidate == target_path or any(candidate_text.endswith(suffix) for suffix in suffixes):
            raw = class_el.get("line-rate")
            return float(raw) if raw is not None else None
    return None


def main(argv: list[str]) -> int:
    """Print gate failures and return a shell exit code."""
    if len(argv) != 2:
        print("usage: coverage_gate.py .artifacts/coverage-be.xml", file=sys.stderr)
        return 2

    xml_path = Path(argv[1])
    if not xml_path.is_file():
        print(f"coverage XML not found: {xml_path}", file=sys.stderr)
        return 2

    root = ET.parse(xml_path).getroot()
    failures: list[str] = []
    for target in REQUIRED_FULL_COVERAGE:
        rate = _line_rate(root, target)
        if rate is None:
            failures.append(f"{target}: missing from coverage report")
        elif rate < 1.0:
            failures.append(f"{target}: {rate * 100:.2f}%")

    if failures:
        print("Coverage gate failed for required 100% modules:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("Coverage gate passed for required 100% modules.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
