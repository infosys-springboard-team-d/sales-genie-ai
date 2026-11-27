from __future__ import annotations

import csv

import pytest

from tools.train_lead_outcome_model import (
    DatasetValidationError,
    _available_features,
    load_and_validate_dataset,
)


FIELDS = [
    "anonymized_lead_id",
    "as_of_date",
    "industry",
    "lead_status_at_snapshot",
    "has_contact_name",
    "has_email",
    "has_phone",
    "recent_activity_count_30d",
    "conversation_count_to_date",
    "has_analysis_need",
    "has_analysis_opportunity",
    "won_within_90_days",
    "outcome_date",
    "observed_through_date",
]

V2_FEATURES = [
    "calls_30d",
    "emails_sent_30d",
    "meetings_30d",
    "replies_30d",
    "has_replied",
    "has_meeting_booked",
    "has_verified_need",
    "has_verified_fit",
    "has_decision_maker_access",
    "has_budget_known",
    "has_timeline_known",
]


def _row(lead_id: str, label: str = "0") -> dict[str, str]:
    return {
        "anonymized_lead_id": lead_id,
        "as_of_date": "2025-01-01T00:00:00Z",
        "industry": "Software",
        "lead_status_at_snapshot": "Contacted",
        "has_contact_name": "1",
        "has_email": "1",
        "has_phone": "0",
        "recent_activity_count_30d": "2",
        "conversation_count_to_date": "1",
        "has_analysis_need": "1",
        "has_analysis_opportunity": "0",
        "won_within_90_days": label,
        "outcome_date": "2025-02-01T00:00:00Z" if label == "1" else "",
        "observed_through_date": "2025-04-15T00:00:00Z",
    }


def _write_rows(
    path, rows: list[dict[str, str]], fields: list[str] = FIELDS
) -> None:
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {field: row.get(field, "") for field in fields} for row in rows
        )


def test_loader_accepts_complete_outcomes_and_sorts_by_snapshot(tmp_path) -> None:
    dataset = tmp_path / "outcomes.csv"
    _write_rows(dataset, [_row("lead_b", "1"), _row("lead_a", "0")])

    frame = load_and_validate_dataset(dataset)

    assert frame["anonymized_lead_id"].tolist() == ["lead_a", "lead_b"]
    assert frame["won_within_90_days"].tolist() == [0, 1]
    assert "has_replied" not in frame.columns
    categorical, numeric = _available_features(frame)
    assert categorical == ["industry", "lead_status_at_snapshot"]
    assert "recent_activity_count_30d" in numeric


def test_loader_accepts_v2_features_without_legacy_numeric_features(tmp_path) -> None:
    dataset = tmp_path / "v2-outcomes.csv"
    fields = [
        "anonymized_lead_id",
        "as_of_date",
        "industry",
        "lead_status_at_snapshot",
        *V2_FEATURES,
        "won_within_90_days",
        "outcome_date",
        "observed_through_date",
    ]
    rows = [_row("lead_a"), _row("lead_b", "1")]
    for row in rows:
        row.update(
            {
                "calls_30d": "2",
                "emails_sent_30d": "3",
                "meetings_30d": "0",
                "replies_30d": "1",
                "has_replied": "1",
                "has_meeting_booked": "0",
                "has_verified_need": "1",
                "has_verified_fit": "1",
                "has_decision_maker_access": "0",
                "has_budget_known": "0",
                "has_timeline_known": "1",
            }
        )
    rows[0]["lead_status_at_snapshot"] = "Nurturing"
    rows[1]["lead_status_at_snapshot"] = "Unqualified"
    _write_rows(dataset, rows, fields)

    frame = load_and_validate_dataset(dataset)
    categorical, numeric = _available_features(frame)

    assert "recent_activity_count_30d" not in frame.columns
    assert categorical == ["industry", "lead_status_at_snapshot"]
    assert numeric == [*V2_FEATURES[4:], *V2_FEATURES[:4]]
    assert frame["has_replied"].tolist() == [1, 1]


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("has_replied", "2", "must be 0 or 1"),
        ("calls_30d", "-1", "non-negative integer"),
    ],
)
def test_loader_validates_optional_features_when_present(
    tmp_path, column: str, value: str, message: str
) -> None:
    dataset = tmp_path / "invalid-optional-feature.csv"
    fields = [*FIELDS, column]
    rows = [_row("lead_a"), _row("lead_b", "1")]
    for row in rows:
        row[column] = "0"
    rows[0][column] = value
    _write_rows(dataset, rows, fields)

    with pytest.raises(DatasetValidationError, match=message):
        load_and_validate_dataset(dataset)


def test_loader_rejects_incomplete_90_day_observation_window(tmp_path) -> None:
    dataset = tmp_path / "outcomes.csv"
    row = _row("lead_a")
    row["observed_through_date"] = "2025-03-01T00:00:00Z"
    _write_rows(dataset, [row, _row("lead_b", "1")])

    with pytest.raises(DatasetValidationError, match="at least 90 days"):
        load_and_validate_dataset(dataset)


def test_loader_rejects_duplicate_lead_ids_to_prevent_split_leakage(tmp_path) -> None:
    dataset = tmp_path / "outcomes.csv"
    _write_rows(dataset, [_row("lead_a"), _row("lead_a", "1")])

    with pytest.raises(DatasetValidationError, match="duplicate lead ID"):
        load_and_validate_dataset(dataset)
