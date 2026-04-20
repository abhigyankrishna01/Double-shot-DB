"""
Evaluation runner for the SQL Data Analyst Agent.

Usage:
    python evaluation/run_eval.py [--backend http://localhost:8000] [--tag aggregation]

Checks:
  - Did the query succeed (step_results with no error)?
  - Do expected tables appear in the generated SQL?
  - Do expected keywords appear in the generated SQL?
  - Did results come back (>= min_rows)?
  - For expected-failure cases: did the system produce a failure explanation?
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

QUERIES_FILE = Path(__file__).parent / "queries.json"


# ── Checkers ──────────────────────────────────────────────────────────────────

def _check_tables(sql: str, expected: list[str]) -> list[str]:
    missing = []
    for table in expected:
        if table.lower() not in sql.lower():
            missing.append(table)
    return missing


def _check_keywords(sql: str, expected: list[str]) -> list[str]:
    missing = []
    for kw in expected:
        if kw.lower() not in sql.lower():
            missing.append(kw)
    return missing


def _evaluate_case(case: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    step_results = data.get("step_results", [])
    successful = [sr for sr in step_results if not sr["error"] and sr["results"] is not None]
    all_sql = " ".join(sr["sql"] for sr in step_results)

    expect_failure = case.get("expect_failure", False)
    result = {
        "id": case["id"],
        "question": case["question"],
        "tags": case["tags"],
        "passed": False,
        "checks": [],
    }

    if expect_failure:
        # Should have failed — check that insight explains the failure
        if not successful and data.get("insight"):
            result["passed"] = True
            result["checks"].append("PASS: system correctly detected failure and explained it")
        else:
            result["checks"].append("FAIL: expected failure but got results")
        return result

    # Must have at least one successful step
    if not successful:
        result["checks"].append(f"FAIL: no successful steps (insight: {data.get('insight', '')[:80]})")
        return result
    result["checks"].append(f"PASS: {len(successful)}/{len(step_results)} step(s) succeeded")

    # Table presence check
    missing_tables = _check_tables(all_sql, case.get("expected_tables", []))
    if missing_tables:
        result["checks"].append(f"FAIL: missing tables in SQL: {missing_tables}")
    else:
        result["checks"].append("PASS: all expected tables present")

    # Keyword check
    missing_kws = _check_keywords(all_sql, case.get("expected_keywords", []))
    if missing_kws:
        result["checks"].append(f"WARN: missing SQL keywords: {missing_kws}")
    else:
        result["checks"].append("PASS: all expected keywords present")

    # Row count check
    total_rows = sum(len(sr["results"]) for sr in successful)
    min_rows = case.get("min_rows", 0)
    if total_rows < min_rows:
        result["checks"].append(f"FAIL: got {total_rows} rows, expected >= {min_rows}")
    else:
        result["checks"].append(f"PASS: {total_rows} row(s) returned")

    # Confidence check
    confidence = data.get("confidence_label", "?")
    result["checks"].append(f"INFO: confidence={confidence}")

    # Pass if no FAIL checks
    result["passed"] = all("FAIL" not in c for c in result["checks"])
    return result


# ── Runner ────────────────────────────────────────────────────────────────────

def run_evaluation(backend_url: str, tag_filter: str | None) -> None:
    cases = json.loads(QUERIES_FILE.read_text())

    if tag_filter:
        cases = [c for c in cases if tag_filter in c.get("tags", [])]

    print(f"\nRunning {len(cases)} test case(s) against {backend_url}\n{'='*60}")

    results = []
    for case in cases:
        print(f"\n[{case['id']}] {case['question']}")
        try:
            resp = requests.post(
                f"{backend_url}/analyze",
                json={"question": case["question"]},
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"  ERROR: {exc}")
            results.append({"id": case["id"], "passed": False, "checks": [f"ERROR: {exc}"]})
            continue

        result = _evaluate_case(case, data)
        for check in result["checks"]:
            print(f"  {check}")

        status = "PASS" if result["passed"] else "FAIL"
        print(f"  → {status}")
        results.append(result)
        time.sleep(1)  # be kind to the rate limiter

    # ── Summary ───────────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed")

    failed = [r for r in results if not r["passed"]]
    if failed:
        print("\nFailed cases:")
        for r in failed:
            print(f"  [{r['id']}] {r.get('question', '')[:60]}")
        sys.exit(1)
    else:
        print("All tests passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run evaluation suite against the analyst agent")
    parser.add_argument("--backend", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--tag", default=None, help="Filter by tag (e.g. aggregation)")
    args = parser.parse_args()
    run_evaluation(args.backend, args.tag)
