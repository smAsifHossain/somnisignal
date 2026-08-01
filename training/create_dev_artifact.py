from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression


FEATURE_NAMES = (
    "mean_nn_ms",
    "median_nn_ms",
    "sdnn_ms",
    "rmssd_ms",
    "pnn50",
    "median_hr_bpm",
    "iqr_hr_bpm",
    "apnea_band_power",
    "lf_power",
    "hf_power",
    "lf_hf_ratio",
    "spectral_entropy",
    "artifact_rate",
)


def create_artifacts(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(20260719)
    negative = rng.normal(-1.5, 0.5, size=(600, len(FEATURE_NAMES)))
    positive = rng.normal(1.5, 0.5, size=(600, len(FEATURE_NAMES)))
    features = np.vstack([negative, positive])
    labels = np.concatenate([np.zeros(negative.shape[0]), np.ones(positive.shape[0])])

    estimator = LogisticRegression(max_iter=2000, random_state=20260719).fit(features, labels)
    raw = np.clip(estimator.predict_proba(features)[:, 1], 1e-6, 1 - 1e-6)
    calibrator = LogisticRegression(random_state=20260719).fit(
        np.log(raw / (1.0 - raw)).reshape(-1, 1), labels
    )
    artifact = {
        "estimator": estimator,
        "calibrator": calibrator,
        "threshold": 0.5,
        "feature_names": FEATURE_NAMES,
    }
    artifact_path = output_dir / "model.joblib"
    joblib.dump(artifact, artifact_path)

    c01 = rng.normal(-1.5, 0.3, size=(480, len(FEATURE_NAMES)))
    b01 = np.vstack(
        [
            rng.normal(1.5, 0.3, size=(50, len(FEATURE_NAMES))),
            rng.normal(-1.5, 0.3, size=(430, len(FEATURE_NAMES))),
        ]
    )
    a01 = np.vstack(
        [
            rng.normal(1.5, 0.3, size=(150, len(FEATURE_NAMES))),
            rng.normal(-1.5, 0.3, size=(330, len(FEATURE_NAMES))),
        ]
    )
    np.savez_compressed(output_dir / "demo_features.npz", a01=a01, b01=b01, c01=c01)

    metadata = {
        "model_version": "dev-unvalidated-0.1.0",
        "release_gate_passed": False,
        "artifact_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        "dataset": "Synthetic development data; not for patient screening",
        "metrics": {},
        "warning": "This artifact exists only for authenticated integration testing.",
    }
    (output_dir / "model_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    create_artifacts(args.output_dir)


if __name__ == "__main__":
    main()
