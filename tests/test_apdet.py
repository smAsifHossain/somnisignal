import numpy as np

from training.apdet_baseline import _minimum_run_mask, detect_apdet_minutes


def test_apdet_requires_fifteen_consecutive_windows() -> None:
    selected = np.r_[np.ones(14), 0, np.ones(15), 0, np.ones(16)].astype(bool)
    detected = _minimum_run_mask(selected)
    assert not detected[:14].any()
    assert detected[15:30].all()
    assert detected[31:].all()


def test_apdet_flat_rr_safely_returns_no_detections() -> None:
    rr = np.full(3600, 1.0)
    times = np.arange(1, 3601, dtype=float)
    output = detect_apdet_minutes(times, rr)
    assert output.detected.size == 0

