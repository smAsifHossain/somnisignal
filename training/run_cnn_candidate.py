"""Run the exported CNN candidate on named public research records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
import wfdb

from app.model import aggregate_night
from app.signal_processing import detect_rr_intervals
from training.rr_cnn import extract_rr_sequence_windows


def _sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    return np.where(
        values >= 0,
        1.0 / (1.0 + np.exp(-values)),
        np.exp(values) / (1.0 + np.exp(values)),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("training/data/apnea-ecg"))
    parser.add_argument(
        "--candidate-dir", type=Path, default=Path("artifacts/candidates")
    )
    parser.add_argument("--records", default="a01,b01,c01")
    args = parser.parse_args()

    metadata = json.loads(
        (args.candidate_dir / "rr_cnn_metadata.json").read_text(encoding="utf-8")
    )
    model_path = args.candidate_dir / "rr_cnn.onnx"
    session = ort.InferenceSession(
        str(model_path), providers=["CPUExecutionProvider"]
    )
    normalization = metadata["input"]
    mean = float(normalization["normalization_mean"])
    standard_deviation = float(
        normalization["normalization_standard_deviation"]
    )
    coefficient = float(metadata["calibration"]["coefficient"][0])
    intercept = float(metadata["calibration"]["intercept"][0])
    threshold = float(metadata["metrics"]["threshold"])

    results: dict[str, dict] = {}
    for record_id in [item.strip() for item in args.records.split(",") if item.strip()]:
        record = wfdb.rdrecord(str(args.data_dir / record_id))
        rr_times, rr, valid_ratio = detect_rr_intervals(
            np.asarray(record.p_signal[:, 0], dtype=np.float64)
        )
        sequences, minutes = extract_rr_sequence_windows(rr_times, rr)
        normalized = ((sequences - mean) / standard_deviation).astype(np.float32)
        logits = session.run(
            ["logit"], {"rr_sequence": normalized[:, None, :]}
        )[0].reshape(-1)
        calibrated = _sigmoid(coefficient * logits + intercept)
        research_result = aggregate_night(
            calibrated,
            threshold=threshold,
            model_version=metadata["model_version"],
        )
        safe_result = aggregate_night(
            calibrated,
            threshold=threshold,
            model_version=metadata["model_version"],
            release_gate_passed=bool(metadata["release_gate_passed"]),
        )
        annotation = wfdb.rdann(str(args.data_dir / record_id), "apn")
        labels = np.asarray([symbol == "A" for symbol in annotation.symbol])
        valid = minutes < labels.size
        actual_apnea_minutes = int(labels[minutes[valid]].sum())
        results[record_id] = {
            "known_dataset_class": (
                "apnea" if record_id.startswith("a") else
                "borderline" if record_id.startswith("b") else "control"
            ),
            "actual_annotated_apnea_minutes": actual_apnea_minutes,
            "cnn_research_outcome_before_gate": research_result.outcome.value,
            "safe_reported_outcome": safe_result.outcome.value,
            "calibrated_research_score": safe_result.risk_score,
            "cnn_flagged_minutes": safe_result.estimated_apnea_minutes,
            "analyzed_minutes": safe_result.analyzed_minutes,
            "rr_valid_ratio": valid_ratio,
            "release_gate_passed": bool(metadata["release_gate_passed"]),
            "warning": "This record was used during final model fitting; this is not an independent test.",
        }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
