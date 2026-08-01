from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.model import aggregate_night, load_model
from app.signal_processing import analyze_ecg_file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path)
    parser.add_argument("--sampling-rate-hz", type=int, default=100)
    parser.add_argument("--artifact-dir", type=Path, default=Path("/app/artifacts"))
    args = parser.parse_args()

    started = time.perf_counter()
    model = load_model(
        args.artifact_dir / "candidates" / "rr_cnn.onnx",
        args.artifact_dir / "candidates" / "rr_cnn_metadata.json",
    )
    analysis = analyze_ecg_file(
        args.record,
        sample_rate_hz=args.sampling_rate_hz,
        minimum_hours=6.0,
        maximum_hours=12.0,
        model_input_kind=model.input_kind,
    )
    probabilities = model.predict_probabilities(analysis.model_inputs)
    result = aggregate_night(
        probabilities,
        threshold=model.threshold,
        model_version=model.version,
        signal_quality=analysis.quality,
        reasons=analysis.reasons,
    )
    print(
        json.dumps(
            {
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "analysis_windows": int(analysis.model_inputs.shape[0]),
                "outcome": result.outcome,
                "signal_quality": result.signal_quality,
                "model_version": result.model_version,
            }
        )
    )


if __name__ == "__main__":
    main()
