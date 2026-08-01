from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import joblib
import numpy as np
import wfdb
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, brier_score_loss, confusion_matrix, roc_curve
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.model import aggregate_night
from app.schemas import ScreeningOutcome
from app.signal_processing import (
    FEATURE_NAMES,
    TARGET_SAMPLE_RATE_HZ,
    detect_rr_intervals,
    extract_feature_windows,
)
from training.download_dataset import RECORDS


DATASET_CITATION = "PhysioNet Apnea-ECG Database v1.0.0, DOI:10.13026/C23W2R"


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _provided_rr(record_path: Path) -> tuple[np.ndarray, np.ndarray, float]:
    record = wfdb.rdrecord(str(record_path))
    annotation = wfdb.rdann(str(record_path), "qrs")
    peaks = np.asarray(annotation.sample, dtype=np.int64)
    rr = np.diff(peaks) / float(record.fs)
    times = peaks[1:] / float(record.fs)
    valid = (rr >= 0.300) & (rr <= 2.000) & np.isfinite(rr)
    valid_ratio = float(valid.mean()) if rr.size else 0.0
    if valid.any() and not valid.all():
        isolated = (~valid) & np.r_[False, valid[:-1]] & np.r_[valid[1:], False]
        indices = np.flatnonzero(valid)
        rr[isolated] = np.interp(np.flatnonzero(isolated), indices, rr[valid])
        keep = valid | isolated
        rr = rr[keep]
        times = times[keep]
    return times, rr, valid_ratio


def load_training_data(
    data_dir: Path,
    *,
    use_provided_qrs: bool,
    cache_dir: Path | None = None,
    record_ids: tuple[str, ...] = RECORDS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    all_features: list[np.ndarray] = []
    all_labels: list[np.ndarray] = []
    all_groups: list[np.ndarray] = []
    all_minutes: list[np.ndarray] = []
    by_record: dict[str, np.ndarray] = {}

    for record_id in record_ids:
        print(f"Extracting {record_id}", flush=True)
        cache_path = None
        if cache_dir is not None:
            mode = "expert-qrs" if use_provided_qrs else "gqrs-v1"
            cache_path = cache_dir / mode / f"{record_id}.npz"
        if cache_path is not None and cache_path.exists():
            cached = np.load(cache_path, allow_pickle=False)
            features = cached["features"]
            minutes = cached["minutes"]
            labels = cached["labels"]
            by_record[record_id] = features
            all_features.append(features)
            all_labels.append(labels)
            all_groups.append(np.repeat(record_id, features.shape[0]))
            all_minutes.append(minutes)
            continue

        record_path = data_dir / record_id
        record = wfdb.rdrecord(str(record_path))
        if int(record.fs) != TARGET_SAMPLE_RATE_HZ:
            raise RuntimeError(f"Unexpected sample rate for {record_id}: {record.fs}")
        if use_provided_qrs:
            rr_times, rr, valid_ratio = _provided_rr(record_path)
        else:
            rr_times, rr, valid_ratio = detect_rr_intervals(
                np.asarray(record.p_signal[:, 0], dtype=np.float64)
            )
        if valid_ratio < 0.80:
            raise RuntimeError(f"RR quality below 80% for {record_id}")

        features, minutes = extract_feature_windows(
            rr_times, rr, artifact_rate=1.0 - valid_ratio
        )
        apnea = wfdb.rdann(str(record_path), "apn")
        minute_labels = np.asarray([1 if symbol == "A" else 0 for symbol in apnea.symbol])
        valid_minutes = minutes < minute_labels.size
        features = features[valid_minutes]
        minutes = minutes[valid_minutes]
        labels = minute_labels[minutes]
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                cache_path, features=features, minutes=minutes, labels=labels
            )
        by_record[record_id] = features
        all_features.append(features)
        all_labels.append(labels)
        all_groups.append(np.repeat(record_id, features.shape[0]))
        all_minutes.append(minutes)

    return (
        np.vstack(all_features),
        np.concatenate(all_labels),
        np.concatenate(all_groups),
        np.concatenate(all_minutes),
        by_record,
    )


def _candidate_factories() -> dict[str, Callable[[], object]]:
    return {
        "logistic_regression": lambda: make_pipeline(
            StandardScaler(),
            LogisticRegression(
                class_weight="balanced", max_iter=3000, random_state=42
            ),
        ),
        "hist_gradient_boosting": lambda: HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=250,
            max_leaf_nodes=15,
            l2_regularization=1.0,
            class_weight="balanced",
            random_state=42,
        ),
    }


def compare_candidates(features: np.ndarray, labels: np.ndarray, groups: np.ndarray):
    scores: dict[str, list[float]] = {name: [] for name in _candidate_factories()}
    for seed in (11, 29, 47):
        splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
        for train_indices, validation_indices in splitter.split(features, labels, groups):
            assert_group_isolation(groups, train_indices, validation_indices)
            for name, factory in _candidate_factories().items():
                model = factory()
                model.fit(features[train_indices], labels[train_indices])
                prediction = model.predict(features[validation_indices])
                scores[name].append(
                    balanced_accuracy_score(labels[validation_indices], prediction)
                )
    means = {name: float(np.mean(values)) for name, values in scores.items()}
    selected = "hist_gradient_boosting" if (
        means["hist_gradient_boosting"] - means["logistic_regression"] > 0.02
    ) else "logistic_regression"
    return selected, means


def assert_group_isolation(
    groups: np.ndarray,
    train_indices: np.ndarray,
    validation_indices: np.ndarray,
) -> None:
    overlap = set(groups[train_indices]).intersection(groups[validation_indices])
    if overlap:
        raise AssertionError("A recording identifier appears in both model folds.")


def out_of_fold_probabilities(
    factory: Callable[[], object],
    features: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
) -> np.ndarray:
    probabilities = np.zeros(labels.shape[0], dtype=float)
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=73)
    for train_indices, validation_indices in splitter.split(features, labels, groups):
        assert_group_isolation(groups, train_indices, validation_indices)
        model = factory()
        model.fit(features[train_indices], labels[train_indices])
        probabilities[validation_indices] = model.predict_proba(features[validation_indices])[:, 1]
    return probabilities


def select_threshold(labels: np.ndarray, probabilities: np.ndarray) -> float:
    false_positive_rate, true_positive_rate, thresholds = roc_curve(labels, probabilities)
    eligible = np.flatnonzero(true_positive_rate >= 0.85)
    if eligible.size == 0:
        return 0.5
    best = eligible[np.argmin(false_positive_rate[eligible])]
    return float(np.clip(thresholds[best], 0.01, 0.99))


def record_metrics(
    groups: np.ndarray,
    calibrated: np.ndarray,
    threshold: float,
) -> dict[str, float | int]:
    truth: list[int] = []
    predicted: list[int] = []
    borderline_inconclusive = 0
    borderline_total = 0
    for record_id in sorted(set(groups)):
        result = aggregate_night(
            calibrated[groups == record_id],
            threshold=threshold,
            model_version="validation",
        )
        if record_id.startswith("b"):
            borderline_total += 1
            borderline_inconclusive += int(
                result.outcome == ScreeningOutcome.inconclusive
            )
            continue
        truth.append(1 if record_id.startswith("a") else 0)
        predicted.append(1 if result.outcome == ScreeningOutcome.elevated_risk else 0)

    tn, fp, fn, tp = confusion_matrix(truth, predicted, labels=[0, 1]).ravel()
    sensitivity = tp / max(tp + fn, 1)
    specificity = tn / max(tn + fp, 1)
    return {
        "sensitivity": float(sensitivity),
        "specificity": float(specificity),
        "balanced_accuracy": float((sensitivity + specificity) / 2.0),
        "borderline_inconclusive": int(borderline_inconclusive),
        "borderline_total": int(borderline_total),
    }


def bootstrap_balanced_accuracy(
    groups: np.ndarray, calibrated: np.ndarray, threshold: float
) -> list[float]:
    record_ids = np.asarray(sorted(record for record in set(groups) if not record.startswith("b")))
    rng = np.random.default_rng(101)
    values: list[float] = []
    for _ in range(1000):
        sample = rng.choice(record_ids, size=record_ids.size, replace=True)
        truth: list[int] = []
        predicted: list[int] = []
        for record_id in sample:
            result = aggregate_night(
                calibrated[groups == record_id],
                threshold=threshold,
                model_version="validation",
            )
            truth.append(1 if record_id.startswith("a") else 0)
            predicted.append(1 if result.outcome == ScreeningOutcome.elevated_risk else 0)
        if len(set(truth)) == 2:
            values.append(balanced_accuracy_score(truth, predicted))
    return [float(value) for value in np.percentile(values, [2.5, 97.5])]


def bootstrap_brier_interval(
    groups: np.ndarray, labels: np.ndarray, calibrated: np.ndarray
) -> list[float]:
    record_ids = np.asarray(sorted(set(groups)))
    rng = np.random.default_rng(103)
    values: list[float] = []
    for _ in range(1000):
        sample = rng.choice(record_ids, size=record_ids.size, replace=True)
        indices = np.concatenate([np.flatnonzero(groups == record_id) for record_id in sample])
        values.append(float(brier_score_loss(labels[indices], calibrated[indices])))
    return [float(value) for value in np.percentile(values, [2.5, 97.5])]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("training/data/apnea-ecg"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--cache-dir", type=Path, default=Path("training/cache"))
    parser.add_argument("--use-provided-qrs", action="store_true")
    parser.add_argument(
        "--records",
        help="Optional comma-separated subset used for resumable feature extraction.",
    )
    parser.add_argument("--extract-only", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    record_ids = RECORDS
    if args.records:
        requested = tuple(item.strip() for item in args.records.split(",") if item.strip())
        unknown = set(requested).difference(RECORDS)
        if unknown:
            raise ValueError("Unknown or excluded training record requested.")
        record_ids = requested

    features, labels, groups, _, by_record = load_training_data(
        args.data_dir,
        use_provided_qrs=args.use_provided_qrs,
        cache_dir=args.cache_dir,
        record_ids=record_ids,
    )
    if args.extract_only:
        print(f"Cached features for {len(record_ids)} records.")
        return
    selected_name, candidate_scores = compare_candidates(features, labels, groups)
    factory = _candidate_factories()[selected_name]
    raw_oof = np.clip(
        out_of_fold_probabilities(factory, features, labels, groups), 1e-6, 1 - 1e-6
    )
    logits = np.log(raw_oof / (1.0 - raw_oof)).reshape(-1, 1)
    calibrator = LogisticRegression(random_state=83).fit(logits, labels)
    calibrated_oof = calibrator.predict_proba(logits)[:, 1]
    threshold = select_threshold(labels, calibrated_oof)
    metrics = record_metrics(groups, calibrated_oof, threshold)
    metrics["balanced_accuracy_95ci"] = bootstrap_balanced_accuracy(
        groups, calibrated_oof, threshold
    )
    metrics["candidate_window_balanced_accuracy"] = candidate_scores
    metrics["minute_brier_score"] = float(brier_score_loss(labels, calibrated_oof))
    metrics["minute_brier_score_95ci"] = bootstrap_brier_interval(
        groups, labels, calibrated_oof
    )
    metrics["threshold"] = threshold
    release_gate_passed = bool(
        metrics["sensitivity"] >= 0.80
        and metrics["specificity"] >= 0.80
        and metrics["balanced_accuracy"] >= 0.80
        and metrics["borderline_inconclusive"] >= 3
    )

    estimator = factory()
    estimator.fit(features, labels)
    artifact = {
        "estimator": estimator,
        "calibrator": calibrator,
        "threshold": threshold,
        "feature_names": FEATURE_NAMES,
    }
    artifact_path = args.output_dir / "model.joblib"
    joblib.dump(artifact, artifact_path)
    np.savez_compressed(
        args.output_dir / "demo_features.npz",
        a01=by_record["a01"],
        b01=by_record["b01"],
        c01=by_record["c01"],
    )
    metadata = {
        "model_version": "physionet-apnea-ecg-1.0.0",
        "release_gate_passed": release_gate_passed,
        "artifact_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        "dataset": DATASET_CITATION,
        "training_commit": _git_commit(),
        "selected_model": selected_name,
        "feature_names": FEATURE_NAMES,
        "metrics": metrics,
        "training_records": len(set(groups)),
        "excluded_records": ["c06 (duplicate of c05)"],
        "qrs_source": "provided expert QRS annotations" if args.use_provided_qrs else "WFDB GQRS detection",
    }
    (args.output_dir / "model_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )

    card = f"""# Sleep-Apnea ECG Screening Model Card

## Intended use

Adult research screening only. This model is not diagnostic and cannot replace
polysomnography or technically adequate home sleep-apnea testing.

## Data and limitations

- {DATASET_CITATION}
- {len(set(groups))} training recordings after excluding duplicate c06.
- The dataset is small, old, and demographically limited, with important age and sex imbalance.
- ECG is a surrogate for respiratory disturbance; a low-risk result cannot rule out apnea.
- Consumer wearable exports may differ materially from the training signals.

## Validation

```json
{json.dumps(metrics, indent=2)}
```

Release gate passed: **{release_gate_passed}**
"""
    (args.output_dir / "MODEL_CARD.md").write_text(card, encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
