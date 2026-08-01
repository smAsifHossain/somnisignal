from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import wfdb
from sklearn.metrics import balanced_accuracy_score, confusion_matrix

from training.apdet_baseline import detect_apdet_minutes
from training.download_dataset import RECORDS
from training.train import _provided_rr


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("training/data/apnea-ecg"))
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/apdet_baseline_metrics.json")
    )
    args = parser.parse_args()

    minute_truth: list[int] = []
    minute_prediction: list[int] = []
    record_truth: list[int] = []
    record_prediction: list[int] = []
    per_record: dict[str, dict[str, float | int]] = {}

    for record_id in RECORDS:
        times, rr, _ = _provided_rr(args.data_dir / record_id)
        output = detect_apdet_minutes(times, rr)
        annotations = wfdb.rdann(str(args.data_dir / record_id), "apn")
        labels = np.asarray([symbol == "A" for symbol in annotations.symbol])
        valid = output.minutes < labels.size
        truth = labels[output.minutes[valid]].astype(int)
        prediction = output.detected[valid].astype(int)
        minute_truth.extend(truth.tolist())
        minute_prediction.extend(prediction.tolist())

        detected_minutes = int(prediction.sum())
        per_record[record_id] = {
            "analyzed_minutes": int(prediction.size),
            "detected_minutes": detected_minutes,
        }
        if record_id.startswith(("a", "c")):
            record_truth.append(int(record_id.startswith("a")))
            # Historical apdet record classification is based on detected burden;
            # use SomniSignal's predeclared 100-minute nightly release boundary.
            record_prediction.append(int(detected_minutes >= 100))

    tn, fp, fn, tp = confusion_matrix(
        record_truth, record_prediction, labels=[0, 1]
    ).ravel()
    sensitivity = tp / max(tp + fn, 1)
    specificity = tn / max(tn + fp, 1)
    metrics = {
        "implementation": "apdet_style_scipy_reproduction",
        "minute_balanced_accuracy": float(
            balanced_accuracy_score(minute_truth, minute_prediction)
        ),
        "sensitivity": float(sensitivity),
        "specificity": float(specificity),
        "balanced_accuracy": float((sensitivity + specificity) / 2.0),
        "release_gate_passed": bool(
            sensitivity >= 0.80
            and specificity >= 0.80
            and (sensitivity + specificity) / 2.0 >= 0.80
        ),
        "per_record": per_record,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()

