from __future__ import annotations

import numpy as np

from tools.train_synthetic_scoring_prototype import (
    FEATURES,
    generate_synthetic_dataset,
    train_and_evaluate,
    write_synthetic_csv,
)


def test_synthetic_dataset_is_reproducible_and_has_expected_shape() -> None:
    features, labels = generate_synthetic_dataset(sample_count=500, seed=7)
    repeated_features, repeated_labels = generate_synthetic_dataset(
        sample_count=500, seed=7
    )

    assert features.shape == (500, len(FEATURES))
    assert labels.shape == (500,)
    assert set(np.unique(labels)) == {0, 1}
    assert np.array_equal(features, repeated_features)
    assert np.array_equal(labels, repeated_labels)


def test_training_reports_holdout_metrics_and_disclaims_acceptance() -> None:
    _, report, features, labels = train_and_evaluate(sample_count=1_000, seed=19)

    assert report["train_count"] + report["holdout_count"] == 1_000
    assert report["holdout_metrics"]["accuracy"] >= 0
    assert report["holdout_metrics"]["accuracy"] <= 1
    assert report["milestone_2_acceptance_eligible"] is False
    assert report["evaluation_type"] == "synthetic_simulation_only"
    assert features.shape[0] == labels.shape[0]


def test_csv_output_includes_synthetic_label_header(tmp_path) -> None:
    features, labels = generate_synthetic_dataset(sample_count=100, seed=3)
    path = tmp_path / "synthetic.csv"

    write_synthetic_csv(path, features, labels)

    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.endswith("won_within_90_days")
