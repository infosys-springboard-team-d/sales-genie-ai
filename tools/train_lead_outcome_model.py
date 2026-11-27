from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path.home() / "Downloads" / "milestone_2_scoring_outcomes_dataset.csv"
DEFAULT_OUTPUT_DIR = ROOT / "resource" / "lead_outcome_candidate"
TARGET = "won_within_90_days"
ID_COLUMN = "anonymized_lead_id"
DATE_COLUMN = "as_of_date"
CATEGORICAL_FEATURES = ("industry", "lead_status_at_snapshot")
BOOLEAN_FEATURES = (
    "has_contact_name",
    "has_email",
    "has_phone",
    "has_analysis_need",
    "has_analysis_opportunity",
    "has_replied",
    "has_meeting_booked",
    "has_verified_need",
    "has_verified_fit",
    "has_decision_maker_access",
    "has_budget_known",
    "has_timeline_known",
)
COUNT_FEATURES = (
    "recent_activity_count_30d",
    "conversation_count_to_date",
    "calls_30d",
    "emails_sent_30d",
    "meetings_30d",
    "replies_30d",
)
FEATURES = (*CATEGORICAL_FEATURES, *BOOLEAN_FEATURES, *COUNT_FEATURES)
REQUIRED_COLUMNS = {
    ID_COLUMN,
    DATE_COLUMN,
    *CATEGORICAL_FEATURES,
    TARGET,
    "outcome_date",
    "observed_through_date",
}
NUMERIC_FEATURES = (*BOOLEAN_FEATURES, *COUNT_FEATURES)
TERMINAL_STATUSES = {"won", "lost"}
FEATURE_SET_VERSION = "lead_outcome_snapshot_features_v1"
SEED = 20261104


class DatasetValidationError(ValueError):
    pass


def _parse_utc(value: str, *, column: str, row_number: int) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DatasetValidationError(
            f"Row {row_number}: {column} must be an ISO 8601 date/time."
        ) from error
    if parsed.tzinfo is None:
        raise DatasetValidationError(
            f"Row {row_number}: {column} must include a timezone."
        )
    return parsed.astimezone(timezone.utc)


def load_and_validate_dataset(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise DatasetValidationError(f"Dataset file does not exist: {path}")

    with path.open(encoding="utf-8-sig", newline="") as dataset_file:
        reader = csv.DictReader(dataset_file)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise DatasetValidationError(
                f"Dataset is missing required columns: {sorted(missing)}"
            )
        if len(columns) != len(reader.fieldnames or []):
            raise DatasetValidationError("Dataset contains duplicate column names.")
        rows = list(reader)

    if not rows:
        raise DatasetValidationError("Dataset has no data rows.")

    seen_ids: set[str] = set()
    parsed_rows: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=2):
        lead_id = (row.get(ID_COLUMN) or "").strip()
        if not lead_id:
            raise DatasetValidationError(f"Row {row_number}: lead ID is blank.")
        if lead_id in seen_ids:
            raise DatasetValidationError(
                f"Row {row_number}: duplicate lead ID. Provide one snapshot per "
                "lead for this evaluation."
            )
        seen_ids.add(lead_id)

        snapshot = _parse_utc(
            (row.get(DATE_COLUMN) or "").strip(),
            column=DATE_COLUMN,
            row_number=row_number,
        )
        observed_through = _parse_utc(
            (row.get("observed_through_date") or "").strip(),
            column="observed_through_date",
            row_number=row_number,
        )
        if observed_through < snapshot + timedelta(days=90):
            raise DatasetValidationError(
                f"Row {row_number}: observed_through_date must be at least "
                "90 days after as_of_date."
            )

        status = (row.get("lead_status_at_snapshot") or "").strip()
        if not status or status.casefold() in TERMINAL_STATUSES:
            raise DatasetValidationError(
                f"Row {row_number}: lead_status_at_snapshot must be a non-terminal "
                "status known at the snapshot."
            )

        normalized: dict[str, Any] = {
            ID_COLUMN: lead_id,
            DATE_COLUMN: snapshot,
            "industry": (row.get("industry") or "").strip() or "Unknown",
            "lead_status_at_snapshot": status,
            "outcome_date": None,
            "observed_through_date": observed_through,
        }
        for column in BOOLEAN_FEATURES:
            if column not in columns:
                continue
            value = (row.get(column) or "").strip()
            if value not in {"0", "1"}:
                raise DatasetValidationError(
                    f"Row {row_number}: {column} must be 0 or 1."
                )
            normalized[column] = int(value)
        for column in COUNT_FEATURES:
            if column not in columns:
                continue
            value = (row.get(column) or "").strip()
            try:
                count = int(value)
            except ValueError as error:
                raise DatasetValidationError(
                    f"Row {row_number}: {column} must be a non-negative integer."
                ) from error
            if count < 0:
                raise DatasetValidationError(
                    f"Row {row_number}: {column} must be a non-negative integer."
                )
            normalized[column] = count

        label = (row.get(TARGET) or "").strip()
        if label not in {"0", "1"}:
            raise DatasetValidationError(
                f"Row {row_number}: {TARGET} must be 0 or 1."
            )
        normalized[TARGET] = int(label)
        raw_outcome_date = (row.get("outcome_date") or "").strip()
        if label == "1":
            if not raw_outcome_date:
                raise DatasetValidationError(
                    f"Row {row_number}: a Won outcome requires outcome_date."
                )
            outcome_date = _parse_utc(
                raw_outcome_date,
                column="outcome_date",
                row_number=row_number,
            )
            if not snapshot <= outcome_date <= snapshot + timedelta(days=90):
                raise DatasetValidationError(
                    f"Row {row_number}: Won outcome is outside the 90-day window."
                )
            normalized["outcome_date"] = outcome_date
        elif raw_outcome_date:
            raise DatasetValidationError(
                f"Row {row_number}: outcome_date must be blank when {TARGET}=0."
            )
        parsed_rows.append(normalized)

    frame = pd.DataFrame(parsed_rows)
    if frame[TARGET].nunique() != 2:
        raise DatasetValidationError(
            "Dataset must contain both Won and not-Won outcomes."
        )
    return frame.sort_values([DATE_COLUMN, ID_COLUMN], kind="stable").reset_index(
        drop=True
    )


def _available_features(frame: pd.DataFrame) -> tuple[list[str], list[str]]:
    categorical = [
        column for column in CATEGORICAL_FEATURES if column in frame.columns
    ]
    numeric = [column for column in NUMERIC_FEATURES if column in frame.columns]
    return categorical, numeric


def _build_pipeline(
    model: Any, categorical_features: list[str], numeric_features: list[str]
) -> Pipeline:
    preprocess = ColumnTransformer(
        transformers=[
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore"),
                categorical_features,
            ),
            ("numeric", "passthrough", numeric_features),
        ]
    )
    return Pipeline([("preprocess", preprocess), ("model", model)])


def _wilson_interval(successes: int, total: int) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z**2 / total
    center = (proportion + z**2 / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total + z**2 / (4 * total**2)
        )
        / denominator
    )
    return [max(0.0, center - margin), min(1.0, center + margin)]


def train_evaluate_and_save(
    dataset_path: Path, output_dir: Path
) -> dict[str, Any]:
    frame = load_and_validate_dataset(dataset_path)
    categorical_features, numeric_features = _available_features(frame)
    features = [*categorical_features, *numeric_features]
    if not features:
        raise DatasetValidationError(
            "Dataset must contain at least one recognized snapshot feature."
        )
    split_index = int(len(frame) * 0.8)
    if split_index < 100 or len(frame) - split_index < 50:
        raise DatasetValidationError(
            "Need at least 100 older training rows and 50 newer holdout rows."
        )

    training = frame.iloc[:split_index]
    holdout = frame.iloc[split_index:]
    x_train = training[features]
    y_train = training[TARGET]
    x_holdout = holdout[features]
    y_holdout = holdout[TARGET]

    candidates = {
        "logistic_regression": LogisticRegression(max_iter=2000),
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            min_samples_leaf=4,
            max_features="sqrt",
            random_state=SEED,
            n_jobs=1,
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_iter=150,
            max_leaf_nodes=15,
            l2_regularization=1.0,
            random_state=SEED,
        ),
    }
    splitter = TimeSeriesSplit(n_splits=5)
    cross_validation: dict[str, dict[str, Any]] = {}
    for name, estimator in candidates.items():
        pipeline = _build_pipeline(
            estimator, categorical_features, numeric_features
        )
        fold_scores = cross_val_score(
            pipeline,
            x_train,
            y_train,
            cv=splitter,
            scoring="accuracy",
            n_jobs=1,
        )
        cross_validation[name] = {
            "fold_accuracy": [float(value) for value in fold_scores],
            "mean_accuracy": float(fold_scores.mean()),
            "std_accuracy": float(fold_scores.std()),
        }

    selected_name = max(
        candidates,
        key=lambda name: cross_validation[name]["mean_accuracy"],
    )
    selected_pipeline = _build_pipeline(
        candidates[selected_name], categorical_features, numeric_features
    )
    selected_pipeline.fit(x_train, y_train)
    predictions = selected_pipeline.predict(x_holdout)
    correct = int((predictions == y_holdout.to_numpy()).sum())
    holdout_accuracy = accuracy_score(y_holdout, predictions)
    matrix = confusion_matrix(y_holdout, predictions, labels=[0, 1])
    baseline_accuracy = max(float((y_holdout == 0).mean()), float((y_holdout == 1).mean()))

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "lead_outcome_candidate.joblib"
    joblib.dump(selected_pipeline, model_path)
    digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    metrics: dict[str, Any] = {
        "evaluation_type": "user_provided_historical_outcomes",
        "dataset_source_file": dataset_path.name,
        "dataset_sha256": digest,
        "rows": int(len(frame)),
        "distinct_leads": int(frame[ID_COLUMN].nunique()),
        "positive_count": int(frame[TARGET].sum()),
        "negative_count": int((frame[TARGET] == 0).sum()),
        "snapshot_start_utc": frame[DATE_COLUMN].min().isoformat(),
        "snapshot_end_utc": frame[DATE_COLUMN].max().isoformat(),
        "split_method": "chronological 80/20 by snapshot date; one snapshot per lead",
        "train_count": int(len(training)),
        "holdout_count": int(len(holdout)),
        "holdout_start_utc": holdout[DATE_COLUMN].min().isoformat(),
        "positive_label": "Won within 90 days after the scoring snapshot",
        "feature_set_version": FEATURE_SET_VERSION,
        "feature_selection": (
            "Use every recognized as-of-snapshot feature present in the input "
            "file; no feature-subset search. Model candidates are selected only "
            "by training-period time-series cross-validation."
        ),
        "features": features,
        "selected_model": selected_name,
        "model_selection": "highest mean accuracy in 5-fold expanding TimeSeriesSplit on training period",
        "training_period_cross_validation": cross_validation,
        "holdout_metrics": {
            "accuracy": float(holdout_accuracy),
            "accuracy_95_percent_wilson_interval": _wilson_interval(
                correct, len(y_holdout)
            ),
            "balanced_accuracy": float(balanced_accuracy_score(y_holdout, predictions)),
            "precision": float(
                precision_score(y_holdout, predictions, zero_division=0)
            ),
            "recall": float(recall_score(y_holdout, predictions, zero_division=0)),
            "f1": float(f1_score(y_holdout, predictions, zero_division=0)),
            "confusion_matrix_labels_0_1": matrix.tolist(),
            "majority_class_baseline_accuracy": baseline_accuracy,
            "actual_positive_count": int(y_holdout.sum()),
            "correct_predictions": correct,
        },
        "acceptance_target_accuracy": 0.85,
        "target_met_on_holdout": bool(holdout_accuracy >= 0.85),
        "production_approved": False,
        "production_status": (
            "not_met"
            if holdout_accuracy < 0.85
            else "holdout_threshold_met_pending_independent_review"
        ),
        "candidate_model_file": model_path.name,
        "scikit_learn_version": sklearn.__version__,
        "limitations": [
            "The supplied file's provenance and labels were not independently audited.",
            "The latest-period holdout contains 100 leads; results have sampling uncertainty.",
            "This candidate is not integrated into SalesGenie production scoring.",
            "No email draft text or human email-review labels are present in this dataset.",
        ],
        "interpretation": (
            "The holdout result is the measured accuracy on later-dated supplied "
            "leads only. It must not be represented as a general guarantee or used "
            "to claim production approval."
        ),
    }
    (output_dir / "evaluation.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and evaluate lead outcome prediction with a chronological "
            "holdout. The candidate is not deployed."
        )
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    report = train_evaluate_and_save(args.dataset, args.output_dir)
    holdout = report["holdout_metrics"]
    print(f"Rows/leads: {report['rows']}/{report['distinct_leads']}")
    print(f"Selected model: {report['selected_model']}")
    print(f"Chronological holdout accuracy: {holdout['accuracy']:.1%}")
    print(
        "95% Wilson interval: "
        f"{holdout['accuracy_95_percent_wilson_interval'][0]:.1%}-"
        f"{holdout['accuracy_95_percent_wilson_interval'][1]:.1%}"
    )
    print(f"85% target met: {report['target_met_on_holdout']}")
    print(f"Production approved: {report['production_approved']}")
    print(f"Evaluation: {args.output_dir / 'evaluation.json'}")


if __name__ == "__main__":
    main()
