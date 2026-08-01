import json
import shutil
from pathlib import Path

import joblib
import numpy as np
import pytest

from app.model import aggregate_night, load_model
from app.schemas import ScreeningOutcome, SignalQuality
from training.create_dev_artifact import create_artifacts


def test_nightly_aggregation_boundaries() -> None:
    low = aggregate_night(np.zeros(480), threshold=0.5, model_version="test")
    assert low.outcome == ScreeningOutcome.low_risk
    assert low.estimated_apnea_minutes == 0

    borderline = aggregate_night(
        np.r_[np.ones(50), np.zeros(430)], threshold=0.5, model_version="test"
    )
    assert borderline.outcome == ScreeningOutcome.inconclusive

    elevated = aggregate_night(
        np.r_[np.ones(100), np.zeros(380)], threshold=0.5, model_version="test"
    )
    assert elevated.outcome == ScreeningOutcome.elevated_risk


def test_quality_failure_is_inconclusive() -> None:
    result = aggregate_night(
        np.ones(480),
        threshold=0.5,
        model_version="test",
        signal_quality=SignalQuality.fail,
        reasons=["bad signal"],
    )
    assert result.outcome == ScreeningOutcome.inconclusive
    assert result.risk_score is None


def test_failed_release_gate_forces_inconclusive_research_output() -> None:
    result = aggregate_night(
        np.ones(480),
        threshold=0.5,
        model_version="unvalidated",
        release_gate_passed=False,
    )
    assert result.outcome == ScreeningOutcome.inconclusive
    assert result.risk_score == 1.0
    assert result.estimated_apnea_minutes == 480
    assert any("release gate" in reason for reason in result.reasons)


def test_model_load_is_deterministic_and_hash_checked(tmp_path: Path) -> None:
    create_artifacts(tmp_path)
    first = load_model(tmp_path / "model.joblib", tmp_path / "model_metadata.json")
    second = load_model(tmp_path / "model.joblib", tmp_path / "model_metadata.json")
    sample = np.zeros((3, len(first.feature_names)))
    np.testing.assert_allclose(
        first.predict_probabilities(sample), second.predict_probabilities(sample)
    )

    with (tmp_path / "model.joblib").open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(RuntimeError, match="integrity"):
        load_model(tmp_path / "model.joblib", tmp_path / "model_metadata.json")


def test_model_load_rejects_wrong_feature_schema(tmp_path: Path) -> None:
    create_artifacts(tmp_path)
    artifact_path = tmp_path / "model.joblib"
    artifact = joblib.load(artifact_path)
    artifact["feature_names"] = tuple(reversed(artifact["feature_names"]))
    joblib.dump(artifact, artifact_path)

    metadata_path = tmp_path / "model_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.pop("artifact_sha256", None)
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(RuntimeError, match="feature schema"):
        load_model(artifact_path, metadata_path)


def test_rr_cnn_load_is_deterministic_and_hash_checked(tmp_path: Path) -> None:
    source_dir = Path("artifacts/candidates")
    model_path = tmp_path / "rr_cnn.onnx"
    external_path = tmp_path / "rr_cnn.onnx.data"
    metadata_path = tmp_path / "rr_cnn_metadata.json"
    shutil.copyfile(source_dir / model_path.name, model_path)
    shutil.copyfile(source_dir / external_path.name, external_path)
    shutil.copyfile(source_dir / metadata_path.name, metadata_path)

    first = load_model(model_path, metadata_path)
    second = load_model(model_path, metadata_path)
    sample = np.full((3, first.sequence_length), 0.8, dtype=np.float32)
    np.testing.assert_allclose(
        first.predict_probabilities(sample),
        second.predict_probabilities(sample),
    )
    assert first.input_kind == "rr_sequence"
    assert first.version == "somnisignal-rr-cnn-1.0.0"

    with external_path.open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(RuntimeError, match="integrity"):
        load_model(model_path, metadata_path)
