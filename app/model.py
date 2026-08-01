from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from app.schemas import ScreeningOutcome, ScreeningResult, SignalQuality
from app.signal_processing import FEATURE_NAMES, RR_SEQUENCE_LENGTH


@dataclass(frozen=True)
class ModelBundle:
    threshold: float
    input_kind: str
    metadata: dict[str, Any]
    estimator: Any = None
    calibrator: Any = None
    feature_names: tuple[str, ...] = ()
    session: Any = None
    input_name: str | None = None
    output_name: str | None = None
    normalization_mean: float = 0.0
    normalization_standard_deviation: float = 1.0
    calibration_coefficient: float = 1.0
    calibration_intercept: float = 0.0
    sequence_length: int = 0

    @property
    def version(self) -> str:
        return str(self.metadata.get("model_version", "unknown"))

    @property
    def release_gate_passed(self) -> bool:
        return bool(self.metadata.get("release_gate_passed", False))

    def predict_probabilities(self, model_inputs: np.ndarray) -> np.ndarray:
        values = np.asarray(model_inputs)
        if values.ndim != 2:
            raise ValueError("Model input must be a two-dimensional window matrix.")
        if values.shape[0] == 0:
            return np.empty(0, dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("Model input contains non-finite values.")

        if self.input_kind == "rr_sequence":
            if values.shape[1] != self.sequence_length:
                raise ValueError("RR sequence length does not match the model artifact.")
            normalized = (
                (values.astype(np.float32) - self.normalization_mean)
                / self.normalization_standard_deviation
            ).astype(np.float32, copy=False)
            logits = np.asarray(
                self.session.run(
                    [self.output_name],
                    {self.input_name: normalized[:, None, :]},
                )[0],
                dtype=float,
            ).reshape(-1)
            calibrated_logits = (
                self.calibration_coefficient * logits + self.calibration_intercept
            )
            return _sigmoid(calibrated_logits)

        if self.input_kind == "hrv_features":
            if values.shape[1] != len(self.feature_names):
                raise ValueError("HRV feature schema does not match the model artifact.")
            raw = np.asarray(self.estimator.predict_proba(values)[:, 1], dtype=float)
            raw = np.clip(raw, 1e-6, 1 - 1e-6)
            logits = np.log(raw / (1.0 - raw)).reshape(-1, 1)
            return np.asarray(
                self.calibrator.predict_proba(logits)[:, 1], dtype=float
            )

        raise RuntimeError(f"Unsupported model input kind: {self.input_kind}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    result = np.empty_like(values)
    positive = values >= 0
    result[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    negative_exp = np.exp(values[~positive])
    result[~positive] = negative_exp / (1.0 + negative_exp)
    return result


def _load_rr_cnn(model_path: Path, metadata: dict[str, Any]) -> ModelBundle:
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError("ONNX Runtime is unavailable.") from exc

    input_metadata = metadata.get("input", {})
    if input_metadata.get("kind") != "rr_sequence":
        raise RuntimeError("CNN metadata does not declare RR-sequence input.")
    sequence_length = int(input_metadata.get("sequence_length", 0))
    if sequence_length != RR_SEQUENCE_LENGTH:
        raise RuntimeError("CNN sequence schema does not match the inference pipeline.")

    mean = float(input_metadata.get("normalization_mean", float("nan")))
    standard_deviation = float(
        input_metadata.get("normalization_standard_deviation", float("nan"))
    )
    if not np.isfinite(mean) or not np.isfinite(standard_deviation) or standard_deviation <= 0:
        raise RuntimeError("CNN normalization metadata is invalid.")

    calibration = metadata.get("calibration", {})
    try:
        coefficient = float(calibration["coefficient"][0])
        intercept = float(calibration["intercept"][0])
        threshold = float(metadata["metrics"]["threshold"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError("CNN calibration metadata is invalid.") from exc
    if not all(np.isfinite([coefficient, intercept, threshold])):
        raise RuntimeError("CNN calibration metadata is not finite.")
    if not 0.0 < threshold < 1.0:
        raise RuntimeError("Model threshold is outside the valid probability range.")

    expected_files = metadata.get("artifact_files_sha256") or {
        model_path.name: metadata.get("artifact_sha256")
    }
    if model_path.name not in expected_files:
        raise RuntimeError("CNN metadata does not contain the model artifact hash.")
    for filename, expected_hash in expected_files.items():
        artifact_path = model_path.parent / filename
        if Path(filename).name != filename or not artifact_path.is_file():
            raise RuntimeError("CNN artifact set is incomplete.")
        if not expected_hash or _sha256(artifact_path) != expected_hash:
            raise RuntimeError("Model artifact integrity check failed.")

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    try:
        session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
    except Exception as exc:
        raise RuntimeError("CNN artifact could not be loaded.") from exc
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 1:
        raise RuntimeError("CNN artifact has an unexpected input/output schema.")

    return ModelBundle(
        threshold=threshold,
        input_kind="rr_sequence",
        metadata=metadata,
        session=session,
        input_name=inputs[0].name,
        output_name=outputs[0].name,
        normalization_mean=mean,
        normalization_standard_deviation=standard_deviation,
        calibration_coefficient=coefficient,
        calibration_intercept=intercept,
        sequence_length=sequence_length,
    )


def _load_feature_model(model_path: Path, metadata: dict[str, Any]) -> ModelBundle:
    artifact = joblib.load(model_path)
    expected_hash = metadata.get("artifact_sha256")
    if expected_hash and _sha256(model_path) != expected_hash:
        raise RuntimeError("Model artifact integrity check failed.")

    feature_names = tuple(artifact["feature_names"])
    if feature_names != FEATURE_NAMES:
        raise RuntimeError("Model feature schema does not match the inference pipeline.")
    metadata_features = metadata.get("feature_names")
    if metadata_features is not None and tuple(metadata_features) != feature_names:
        raise RuntimeError("Model metadata feature schema does not match the artifact.")
    threshold = float(artifact["threshold"])
    if not 0.0 < threshold < 1.0:
        raise RuntimeError("Model threshold is outside the valid probability range.")

    return ModelBundle(
        threshold=threshold,
        input_kind="hrv_features",
        metadata=metadata,
        estimator=artifact["estimator"],
        calibrator=artifact["calibrator"],
        feature_names=feature_names,
    )


def load_model(model_path: Path, metadata_path: Path) -> ModelBundle:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    input_kind = metadata.get("input", {}).get("kind")
    if model_path.suffix.lower() == ".onnx" or input_kind == "rr_sequence":
        return _load_rr_cnn(model_path, metadata)
    return _load_feature_model(model_path, metadata)


def aggregate_night(
    probabilities: np.ndarray,
    *,
    threshold: float,
    model_version: str,
    signal_quality: SignalQuality = SignalQuality.pass_,
    reasons: list[str] | None = None,
    release_gate_passed: bool = True,
) -> ScreeningResult:
    reasons = list(reasons or [])
    if signal_quality == SignalQuality.fail or probabilities.size == 0:
        return ScreeningResult(
            outcome=ScreeningOutcome.inconclusive,
            analyzed_minutes=int(probabilities.size),
            signal_quality=SignalQuality.fail,
            reasons=reasons or ["The recording did not pass signal-quality checks."],
            model_version=model_version,
        )

    predicted = probabilities >= threshold
    apnea_minutes = int(predicted.sum())
    if predicted.size >= 60:
        max_hour = int(np.convolve(predicted.astype(int), np.ones(60, dtype=int), mode="valid").max())
    else:
        max_hour = apnea_minutes

    if apnea_minutes >= 100 and max_hour >= 10:
        outcome = ScreeningOutcome.elevated_risk
    elif apnea_minutes < 5:
        outcome = ScreeningOutcome.low_risk
    else:
        outcome = ScreeningOutcome.inconclusive
        reasons.append("The estimated burden falls in the model's borderline range.")

    # A technically valid model output is not a clinical screening decision until
    # the locked, patient-grouped release criteria have been met.  Keep the score
    # and estimated minutes visible for research debugging, but never display a
    # positive or negative patient-facing outcome from an unvalidated artifact.
    if not release_gate_passed:
        outcome = ScreeningOutcome.inconclusive
        reasons.append(
            "The research model has not passed its validation release gate; "
            "no apnea decision can be reported."
        )

    return ScreeningResult(
        outcome=outcome,
        risk_score=float(np.clip(probabilities.mean(), 0.0, 1.0)),
        analyzed_minutes=int(probabilities.size),
        estimated_apnea_minutes=apnea_minutes,
        signal_quality=signal_quality,
        reasons=reasons,
        model_version=model_version,
    )
