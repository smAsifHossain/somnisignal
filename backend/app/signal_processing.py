from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import signal as scipy_signal
from wfdb import processing as wfdb_processing

from app.ecg_inputs import InputValidationError, load_ecg_input
from app.schemas import SignalQuality


TARGET_SAMPLE_RATE_HZ = 100
RR_SEQUENCE_SAMPLE_RATE_HZ = 4
RR_SEQUENCE_WINDOW_SECONDS = 5 * 60
RR_SEQUENCE_LENGTH = RR_SEQUENCE_SAMPLE_RATE_HZ * RR_SEQUENCE_WINDOW_SECONDS
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


@dataclass(frozen=True)
class SignalAnalysis:
    features: np.ndarray
    quality: SignalQuality
    reasons: list[str] = field(default_factory=list)

    @property
    def model_inputs(self) -> np.ndarray:
        """Return the model-ready windows.

        ``features`` is retained as the public attribute for compatibility with
        the original feature-model tooling. For the deployed RR-CNN it contains
        fixed-length RR sequences instead of handcrafted HRV features.
        """

        return self.features


def read_ecg_csv_gz(
    path: Path,
    *,
    sample_rate_hz: int,
    minimum_hours: float,
    maximum_hours: float,
) -> tuple[np.ndarray, SignalQuality, list[str]]:
    ecg, detected_rate = load_ecg_input(
        path,
        sampling_rate_hz=sample_rate_hz,
        ecg_channel=None,
        maximum_hours=maximum_hours,
    )
    return validate_ecg_signal(
        ecg,
        sample_rate_hz=detected_rate,
        minimum_hours=minimum_hours,
        maximum_hours=maximum_hours,
    )


def validate_ecg_signal(
    ecg: np.ndarray,
    *,
    sample_rate_hz: int,
    minimum_hours: float,
    maximum_hours: float,
) -> tuple[np.ndarray, SignalQuality, list[str]]:
    if not minimum_hours > 0 or maximum_hours <= minimum_hours:
        raise RuntimeError("Invalid duration configuration.")
    ecg = np.asarray(ecg, dtype=np.float32).reshape(-1)
    maximum_samples = int(maximum_hours * 3600 * sample_rate_hz)
    if ecg.size > maximum_samples:
        raise InputValidationError("Recording exceeds the 12-hour limit.")
    minimum_samples = int(minimum_hours * 3600 * sample_rate_hz)
    if ecg.size < minimum_samples:
        return ecg, SignalQuality.fail, ["Recording is shorter than six hours."]

    finite = np.isfinite(ecg)
    finite_ratio = float(finite.mean()) if ecg.size else 0.0
    if finite_ratio < 0.995:
        return ecg, SignalQuality.fail, ["Fewer than 99.5% of ECG samples are finite."]
    if not finite.all():
        indices = np.arange(ecg.size)
        ecg[~finite] = np.interp(indices[~finite], indices[finite], ecg[finite])

    scale = float(np.nanstd(ecg))
    if not math.isfinite(scale) or scale < 1e-6:
        return ecg, SignalQuality.fail, ["The ECG signal is flat or has negligible variation."]

    clipped_fraction = float(
        np.mean(ecg == np.min(ecg)) + np.mean(ecg == np.max(ecg))
    )
    if clipped_fraction > 0.05:
        return ecg, SignalQuality.fail, ["Too much of the ECG signal appears clipped."]

    flat_edges = np.abs(np.diff(ecg)) < max(scale * 1e-5, 1e-7)
    flat_fraction = _sustained_flat_fraction(
        flat_edges,
        minimum_run=max(2, int(round(sample_rate_hz * 0.5))),
    )
    if flat_fraction > 0.20:
        return ecg, SignalQuality.fail, ["Too much of the ECG signal is flatlined."]

    reasons: list[str] = []
    quality = SignalQuality.pass_
    if flat_fraction > 0.05:
        quality = SignalQuality.warn
        reasons.append("The recording contains repeated flat signal segments.")
    if clipped_fraction > 0.01:
        quality = SignalQuality.warn
        reasons.append("The ECG contains possible amplitude clipping.")
    return ecg, quality, reasons


def _sustained_flat_fraction(flat_edges: np.ndarray, *, minimum_run: int) -> float:
    """Return the sample fraction contained in sustained near-constant runs."""

    edges = np.asarray(flat_edges, dtype=bool).reshape(-1)
    if edges.size == 0:
        return 0.0
    padded = np.r_[False, edges, False].astype(np.int8)
    changes = np.diff(padded)
    starts = np.flatnonzero(changes == 1)
    stops = np.flatnonzero(changes == -1)
    run_lengths = stops - starts
    sustained = run_lengths[run_lengths >= minimum_run]
    if sustained.size == 0:
        return 0.0
    # A run of N unchanged edges spans N + 1 ECG samples.
    return float(np.sum(sustained + 1) / (edges.size + 1))


def resample_ecg(ecg: np.ndarray, source_rate_hz: int) -> np.ndarray:
    if source_rate_hz == TARGET_SAMPLE_RATE_HZ:
        return np.asarray(ecg, dtype=np.float64)
    divisor = math.gcd(source_rate_hz, TARGET_SAMPLE_RATE_HZ)
    return scipy_signal.resample_poly(
        np.asarray(ecg, dtype=np.float64),
        TARGET_SAMPLE_RATE_HZ // divisor,
        source_rate_hz // divisor,
    )


def detect_rr_intervals(ecg: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    peaks = np.asarray(
        wfdb_processing.gqrs_detect(
            sig=np.asarray(ecg, dtype=np.float64),
            fs=TARGET_SAMPLE_RATE_HZ,
        ),
        dtype=np.int64,
    )
    if peaks.size < 2:
        return np.array([], dtype=float), np.array([], dtype=float), 0.0

    rr = np.diff(peaks) / TARGET_SAMPLE_RATE_HZ
    times = peaks[1:] / TARGET_SAMPLE_RATE_HZ
    valid = (rr >= 0.300) & (rr <= 2.000) & np.isfinite(rr)
    valid_ratio = float(valid.mean()) if rr.size else 0.0
    if valid.any() and not valid.all():
        isolated = (~valid) & np.r_[False, valid[:-1]] & np.r_[valid[1:], False]
        valid_indices = np.flatnonzero(valid)
        rr[isolated] = np.interp(np.flatnonzero(isolated), valid_indices, rr[valid])
        keep = valid | isolated
        rr = rr[keep]
        times = times[keep]
    return times, rr, valid_ratio


def _band_power(frequencies: np.ndarray, power: np.ndarray, low: float, high: float) -> float:
    mask = (frequencies >= low) & (frequencies < high)
    if mask.sum() < 2:
        return 0.0
    return float(np.trapezoid(power[mask], frequencies[mask]))


def extract_window_features(rr_seconds: np.ndarray, artifact_rate: float) -> np.ndarray:
    rr_ms = rr_seconds * 1000.0
    differences = np.diff(rr_ms)
    heart_rate = 60.0 / rr_seconds

    beat_times = np.cumsum(rr_seconds)
    uniform_times = np.arange(beat_times[0], beat_times[-1], 0.25)
    interpolated_rr = np.interp(uniform_times, beat_times, rr_seconds)
    frequencies, power = scipy_signal.welch(
        interpolated_rr - np.mean(interpolated_rr),
        fs=4.0,
        nperseg=min(256, interpolated_rr.size),
    )
    apnea_power = _band_power(frequencies, power, 0.01, 0.04)
    lf_power = _band_power(frequencies, power, 0.04, 0.15)
    hf_power = _band_power(frequencies, power, 0.15, 0.40)
    positive_power = power[power > 0]
    if positive_power.size:
        distribution = positive_power / positive_power.sum()
        entropy = float(-(distribution * np.log(distribution)).sum() / np.log(distribution.size))
    else:
        entropy = 0.0

    return np.array(
        [
            np.mean(rr_ms),
            np.median(rr_ms),
            np.std(rr_ms, ddof=1),
            np.sqrt(np.mean(np.square(differences))) if differences.size else 0.0,
            np.mean(np.abs(differences) > 50.0) if differences.size else 0.0,
            np.median(heart_rate),
            np.percentile(heart_rate, 75) - np.percentile(heart_rate, 25),
            apnea_power,
            lf_power,
            hf_power,
            lf_power / max(hf_power, 1e-12),
            entropy,
            artifact_rate,
        ],
        dtype=np.float64,
    )


def extract_feature_windows(
    rr_times_seconds: np.ndarray,
    rr_seconds: np.ndarray,
    *,
    artifact_rate: float,
) -> tuple[np.ndarray, np.ndarray]:
    if rr_times_seconds.size == 0:
        return (
            np.empty((0, len(FEATURE_NAMES)), dtype=np.float64),
            np.empty(0, dtype=int),
        )

    duration_minutes = int(rr_times_seconds[-1] // 60)
    rows: list[np.ndarray] = []
    minutes: list[int] = []
    for minute in range(2, max(2, duration_minutes - 2)):
        center = minute * 60.0 + 30.0
        mask = (rr_times_seconds >= center - 150.0) & (rr_times_seconds < center + 150.0)
        window = rr_seconds[mask]
        if window.size < 60:
            continue
        rows.append(extract_window_features(window, artifact_rate))
        minutes.append(minute)
    if not rows:
        return (
            np.empty((0, len(FEATURE_NAMES)), dtype=np.float64),
            np.empty(0, dtype=int),
        )
    return np.vstack(rows), np.asarray(minutes, dtype=int)


def extract_features_from_rr(
    rr_times_seconds: np.ndarray,
    rr_seconds: np.ndarray,
    *,
    artifact_rate: float,
) -> np.ndarray:
    features, _ = extract_feature_windows(
        rr_times_seconds, rr_seconds, artifact_rate=artifact_rate
    )
    return features


def extract_rr_sequence_windows(
    rr_times_seconds: np.ndarray,
    rr_seconds: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Interpolate five-minute RR sequences at 4 Hz, one window per minute."""

    times = np.asarray(rr_times_seconds, dtype=float)
    rr = np.asarray(rr_seconds, dtype=float)
    if times.size < 2 or rr.size != times.size:
        return (
            np.empty((0, RR_SEQUENCE_LENGTH), dtype=np.float32),
            np.empty(0, dtype=int),
        )

    duration_minutes = int(times[-1] // 60)
    rows: list[np.ndarray] = []
    minutes: list[int] = []
    offsets = np.arange(RR_SEQUENCE_LENGTH, dtype=float) / RR_SEQUENCE_SAMPLE_RATE_HZ
    for minute in range(2, max(2, duration_minutes - 2)):
        center = minute * 60.0 + 30.0
        start = center - RR_SEQUENCE_WINDOW_SECONDS / 2
        grid = start + offsets
        if grid[0] < times[0] or grid[-1] > times[-1]:
            continue
        row = np.interp(grid, times, rr)
        if not np.isfinite(row).all():
            continue
        rows.append(row.astype(np.float32))
        minutes.append(minute)
    if not rows:
        return (
            np.empty((0, RR_SEQUENCE_LENGTH), dtype=np.float32),
            np.empty(0, dtype=int),
        )
    return np.vstack(rows), np.asarray(minutes, dtype=int)


def analyze_ecg_file(
    path: Path,
    *,
    sample_rate_hz: int | None,
    ecg_channel: str | None = None,
    minimum_hours: float,
    maximum_hours: float,
    model_input_kind: str = "hrv_features",
) -> SignalAnalysis:
    if model_input_kind not in {"hrv_features", "rr_sequence"}:
        raise RuntimeError(f"Unsupported model input kind: {model_input_kind}")
    ecg, detected_rate = load_ecg_input(
        path,
        sampling_rate_hz=sample_rate_hz,
        ecg_channel=ecg_channel,
        maximum_hours=maximum_hours,
    )
    ecg, quality, reasons = validate_ecg_signal(
        ecg,
        sample_rate_hz=detected_rate,
        minimum_hours=minimum_hours,
        maximum_hours=maximum_hours,
    )
    if quality == SignalQuality.fail:
        width = (
            RR_SEQUENCE_LENGTH
            if model_input_kind == "rr_sequence"
            else len(FEATURE_NAMES)
        )
        return SignalAnalysis(np.empty((0, width)), quality, reasons)

    resampled = resample_ecg(ecg, detected_rate)
    del ecg
    rr_times, rr, valid_ratio = detect_rr_intervals(resampled)
    del resampled
    if valid_ratio < 0.80:
        width = (
            RR_SEQUENCE_LENGTH
            if model_input_kind == "rr_sequence"
            else len(FEATURE_NAMES)
        )
        return SignalAnalysis(
            np.empty((0, width)),
            SignalQuality.fail,
            reasons + ["Fewer than 80% of detected RR intervals are physiologically valid."],
        )

    artifact_rate = 1.0 - valid_ratio
    if model_input_kind == "rr_sequence":
        features, _ = extract_rr_sequence_windows(rr_times, rr)
    elif model_input_kind == "hrv_features":
        features = extract_features_from_rr(
            rr_times, rr, artifact_rate=artifact_rate
        )
    expected_minutes = max(1, int(rr_times[-1] // 60) - 4)
    coverage = features.shape[0] / expected_minutes
    if coverage < 0.50:
        return SignalAnalysis(
            features,
            SignalQuality.fail,
            reasons + ["Too few five-minute ECG windows passed quality checks."],
        )
    if coverage < 0.90 and quality == SignalQuality.pass_:
        quality = SignalQuality.warn
        reasons.append("Some ECG windows were excluded by signal-quality checks.")
    return SignalAnalysis(features, quality, reasons)
