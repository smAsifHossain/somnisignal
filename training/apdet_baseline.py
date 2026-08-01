"""Lightweight Python reproduction of the historical PhysioNet apdet baseline.

The original implementation is a GPL command-line pipeline.  This module
reproduces its published signal-processing stages with NumPy/SciPy so it can be
evaluated inside the same patient-grouped harness as SomniSignal.  It is a
research comparator, not a clinical algorithm and not a drop-in model artifact.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage, signal


@dataclass(frozen=True)
class ApdetOutput:
    minutes: np.ndarray
    detected: np.ndarray
    window_statistics: np.ndarray


def _minimum_run_mask(values: np.ndarray, minimum: int = 15) -> np.ndarray:
    values = np.asarray(values, dtype=bool)
    output = np.zeros(values.shape, dtype=bool)
    padded = np.r_[False, values, False]
    changes = np.flatnonzero(padded[1:] != padded[:-1])
    for start, stop in changes.reshape(-1, 2):
        if stop - start >= minimum:
            output[start:stop] = True
    return output


def _odd_window(size: int, length: int) -> int:
    value = min(size, length if length % 2 else length - 1)
    return max(3, value)


def detect_apdet_minutes(
    rr_times_seconds: np.ndarray,
    rr_seconds: np.ndarray,
) -> ApdetOutput:
    """Return minute decisions using the published apdet threshold sequence.

    Constants follow PhysioNet apdet 1.0.  SciPy's analytic-signal and local
    linear filters replace the historical standalone C utilities, so results
    are reported as an ``apdet_style`` reproducibility baseline rather than as
    byte-for-byte output from the 2002 executables.
    """

    times = np.asarray(rr_times_seconds, dtype=float)
    intervals = np.asarray(rr_seconds, dtype=float)
    valid = (
        np.isfinite(times)
        & np.isfinite(intervals)
        & (intervals >= 0.4)
        & (intervals <= 2.0)
    )
    times = times[valid]
    intervals = intervals[valid]
    if times.size < 600 or times[-1] - times[0] < 15 * 60:
        return ApdetOutput(
            minutes=np.empty(0, dtype=int),
            detected=np.empty(0, dtype=bool),
            window_statistics=np.empty((0, 6), dtype=float),
        )

    uniform_times = np.arange(np.ceil(times[0]), np.floor(times[-1]) + 1.0)
    uniform_rr = np.interp(uniform_times, times, intervals)

    # Historical ldetrend uses a 2*40+1 point local least-squares line.  A
    # first-order Savitzky-Golay trend is the equivalent centered operation.
    trend_window = _odd_window(81, uniform_rr.size)
    trend = signal.savgol_filter(
        uniform_rr, trend_window, polyorder=1, mode="interp"
    )
    filtered = uniform_rr - trend
    filtered = ndimage.uniform_filter1d(filtered, size=5, mode="nearest")

    analytic = signal.hilbert(filtered)
    amplitude = np.abs(analytic)
    frequency = np.abs(np.diff(np.unwrap(np.angle(analytic)), prepend=0.0)) / (
        2.0 * np.pi
    )
    amplitude = ndimage.median_filter(amplitude, size=60, mode="nearest")
    frequency = ndimage.median_filter(frequency, size=60, mode="nearest")
    mean_amplitude = float(np.mean(amplitude))
    if not np.isfinite(mean_amplitude) or mean_amplitude <= 1e-12:
        return ApdetOutput(
            minutes=np.empty(0, dtype=int),
            detected=np.empty(0, dtype=bool),
            window_statistics=np.empty((0, 6), dtype=float),
        )
    amplitude /= mean_amplitude

    midpoint = (float(np.min(amplitude)) + float(np.max(amplitude))) / 2.0
    amplitude_threshold = -0.555 + 1.3 * (midpoint + 1.0) / 2.0

    minute_starts = np.arange(
        int(uniform_times[0]), int(uniform_times[-1]) - 300 + 1, 60, dtype=int
    )
    statistics: list[list[float]] = []
    for start in minute_starts:
        selection = (uniform_times >= start) & (uniform_times < start + 300)
        amp = amplitude[selection]
        freq = frequency[selection]
        if amp.size < 295:
            continue
        statistics.append(
            [
                float(np.mean(amp)),
                float(np.std(amp, ddof=1)),
                float(np.mean(amp >= amplitude_threshold)),
                float(np.mean(freq)),
                float(np.std(freq, ddof=1)),
                float(np.mean(freq <= 0.06)),
            ]
        )

    if not statistics:
        return ApdetOutput(
            minutes=np.empty(0, dtype=int),
            detected=np.empty(0, dtype=bool),
            window_statistics=np.empty((0, 6), dtype=float),
        )

    stats = np.asarray(statistics, dtype=float)
    selected = (
        (stats[:, 0] >= 0.65)
        & (stats[:, 0] <= 2.5)
        & (stats[:, 1] >= 0.0)
        & (stats[:, 1] <= 0.6)
        & (stats[:, 2] >= 0.006)
        & (stats[:, 2] <= 1.0)
        & (stats[:, 3] >= 0.01)
        & (stats[:, 3] <= 0.055)
        & (stats[:, 4] >= 0.0)
        & (stats[:, 4] <= 0.01)
        & (stats[:, 5] >= 0.7)
        & (stats[:, 5] <= 1.0)
    )
    detected = _minimum_run_mask(selected, minimum=15)
    minutes = (minute_starts[: stats.shape[0]] // 60).astype(int)
    return ApdetOutput(minutes=minutes, detected=detected, window_statistics=stats)

