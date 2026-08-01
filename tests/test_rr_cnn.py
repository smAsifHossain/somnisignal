import numpy as np

from app.signal_processing import (
    RR_SEQUENCE_LENGTH as SEQUENCE_LENGTH,
    extract_rr_sequence_windows,
)


def test_rr_sequence_windows_have_fixed_shape_and_minute_alignment() -> None:
    times = np.arange(0.5, 3600.0, 0.8)
    rr = 0.8 + 0.04 * np.sin(2 * np.pi * times / 40.0)
    sequences, minutes = extract_rr_sequence_windows(times, rr)
    assert sequences.ndim == 2
    assert sequences.shape[1] == SEQUENCE_LENGTH
    assert sequences.shape[0] == minutes.size
    assert np.all(np.diff(minutes) == 1)
    assert sequences.dtype == np.float32


def test_rr_sequence_rejects_mismatched_arrays() -> None:
    sequences, minutes = extract_rr_sequence_windows(
        np.arange(10, dtype=float), np.arange(9, dtype=float)
    )
    assert sequences.shape == (0, SEQUENCE_LENGTH)
    assert minutes.size == 0
