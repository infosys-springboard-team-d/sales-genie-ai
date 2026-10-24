from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "resource" / "milestone_1_ai_evaluation_set.csv"
RESULTS = ROOT / "resource" / "milestone_1_ai_evaluation_results.json"
REQUIRED_COLUMNS = {
    "case_id",
    "company_name",
    "industry",
    "contact_name",
    "email",
    "context",
    "expected_facts",
    "expected_need",
    "opportunity_guidance",
}


def write_results(path: Path, report: dict[str, object]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def request_json(
    base_url: str,
    method: str,
    endpoint: str,
    *,
    expected_status: int,
    **kwargs: object,
) -> dict[str, object]:
    response = requests.request(
        method,
        f"{base_url}{endpoint}",
        timeout=210,
        **kwargs,
    )
    if response.status_code != expected_status:
        raise RuntimeError(
            f"{method} {endpoint} returned {response.status_code}: "
            f"{response.text[:1000]}"
        )
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError(f"{method} {endpoint} returned a non-object JSON body.")
    return body


def load_cases(dataset_path: Path) -> list[dict[str, str]]:
    with dataset_path.open(encoding="utf-8-sig", newline="") as dataset_file:
        reader = csv.DictReader(dataset_file)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"Evaluation CSV is missing columns: {sorted(missing)}")
        cases = list(reader)

    if not cases:
        raise ValueError("Evaluation set must contain at least one case.")
    case_ids = [case["case_id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Evaluation case IDs must be unique.")
    for case in cases:
        if any(not case.get(column, "").strip() for column in REQUIRED_COLUMNS):
            raise ValueError(f"Evaluation case {case.get('case_id')} has a blank field.")
    return cases


def evaluate_case(
    base_url: str,
    case: dict[str, str],
) -> dict[str, object]:
    lead_payload = {
        "company_name": case["company_name"],
        "industry": case["industry"],
        "contact_name": case["contact_name"],
        "email": case["email"],
    }
    lead = request_json(
        base_url,
        "POST",
        "/api/v1/leads",
        expected_status=201,
        json=lead_payload,
    )
    lead_id = lead.get("lead_id")
    if not isinstance(lead_id, int):
        raise RuntimeError(f"Lead create response has no integer lead_id: {lead}")

    analysis = request_json(
        base_url,
        "POST",
        f"/api/v1/leads/{lead_id}/analysis",
        expected_status=201,
        json={"context": case["context"]},
    )
    saved = request_json(
        base_url,
        "GET",
        f"/api/v1/leads/{lead_id}/analysis",
        expected_status=200,
    )
    analysis_id = analysis.get("analysis_id")
    if (
        analysis.get("lead_id") != lead_id
        or saved.get("lead_id") != lead_id
        or saved.get("analysis_id") != analysis_id
    ):
        raise RuntimeError(
            f"Saved analysis identity mismatch for {case['case_id']}: "
            f"lead={lead_id}, generated={analysis_id}, saved={saved.get('analysis_id')}"
        )

    return {
        "case_id": case["case_id"],
        "company_name": case["company_name"],
        "expected_facts": case["expected_facts"].split("; "),
        "expected_need": case["expected_need"],
        "opportunity_guidance": case["opportunity_guidance"],
        "lead_id": lead_id,
        "analysis_id": analysis_id,
        "manageable_record_pass": True,
        "analysis": analysis,
        "manual_review": {
            "status": "pending",
            "reviewer": None,
            "review_date": None,
            "accurate": None,
            "failed_criteria": [],
            "notes": None,
        },
    }


def failed_case_result(case: dict[str, str], error: RuntimeError) -> dict[str, object]:
    return {
        "case_id": case["case_id"],
        "company_name": case["company_name"],
        "expected_facts": case["expected_facts"].split("; "),
        "expected_need": case["expected_need"],
        "opportunity_guidance": case["opportunity_guidance"],
        "manageable_record_pass": False,
        "error": str(error),
        "manual_review": {
            "status": "not evaluable",
            "reviewer": None,
            "review_date": None,
            "accurate": None,
            "failed_criteria": [],
            "notes": "The operational flow failed before a saved analysis could be reviewed.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the synthetic Milestone 1 insight evaluation against a local API."
    )
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--output", type=Path, default=RESULTS)
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
    )
    args = parser.parse_args()

    cases = load_cases(args.dataset)
    report: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(args.dataset),
        "api_base_url": args.base_url,
        "model": os.getenv("OLLAMA_MODEL", "llama3.2:latest"),
        "case_count": len(cases),
        "manageable_pass_count": 0,
        "manageable_failure_count": 0,
        "accuracy_review_status": "pending human review",
        "cases": [],
    }
    results = report["cases"]
    assert isinstance(results, list)
    write_results(args.output, report)

    for case in cases:
        try:
            result = evaluate_case(args.base_url, case)
        except RuntimeError as error:
            result = failed_case_result(case, error)
        results.append(result)
        report["manageable_pass_count"] = sum(
            item["manageable_record_pass"] is True for item in results
        )
        report["manageable_failure_count"] = len(results) - int(
            report["manageable_pass_count"]
        )
        write_results(args.output, report)
        outcome = "PASS" if result["manageable_record_pass"] else "FAIL"
        print(f"{outcome} {len(results)}/{len(cases)}: {case['case_id']}")

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["evaluation_status"] = (
        "completed_with_failures"
        if report["manageable_failure_count"]
        else "completed"
    )
    write_results(args.output, report)
    print(
        f"Operational flow: {report['manageable_pass_count']}/{len(cases)} passed; "
        f"{report['manageable_failure_count']} failed. "
        "Insight accuracy remains unscored pending human review."
    )
    print(f"Results: {args.output}")
    if report["manageable_failure_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
