import gzip
import zipfile
from pathlib import Path

import numpy as np
import pyedflib.highlevel
import pytest
import wfdb

from app.ecg_inputs import InputValidationError, detect_upload_suffix, load_ecg_input
from app.signal_processing import (
    FEATURE_NAMES,
    RR_SEQUENCE_LENGTH,
    extract_feature_windows,
    extract_rr_sequence_windows,
    extract_window_features,
    read_ecg_csv_gz,
    validate_ecg_signal,
)


def test_hrv_feature_vector_is_finite() -> None:
    rr = 0.8 + 0.04 * np.sin(np.linspace(0, 20, 400))
    features = extract_window_features(rr, artifact_rate=0.02)
    assert features.shape == (len(FEATURE_NAMES),)
    assert np.isfinite(features).all()
    assert features[-1] == pytest.approx(0.02)


def test_five_minute_windows_advance_one_minute() -> None:
    rr = np.full(3600, 1.0)
    times = np.arange(1, 3601, dtype=float)
    features, minutes = extract_feature_windows(times, rr, artifact_rate=0.0)
    assert features.shape[0] == minutes.size
    assert np.diff(minutes).min() == 1
    assert features.shape[1] == len(FEATURE_NAMES)


def test_rr_sequence_windows_are_model_ready() -> None:
    times = np.arange(0.5, 3600.0, 0.8)
    rr = 0.8 + 0.04 * np.sin(2 * np.pi * times / 40.0)
    sequences, minutes = extract_rr_sequence_windows(times, rr)
    assert sequences.shape == (minutes.size, RR_SEQUENCE_LENGTH)
    assert sequences.dtype == np.float32
    assert np.isfinite(sequences).all()
    assert np.all(np.diff(minutes) == 1)


def test_quantized_ecg_is_not_mistaken_for_flatline() -> None:
    samples = np.arange(6 * 3600 * 80, dtype=float) / 80.0
    waveform = (
        np.sin(2 * np.pi * 1.1 * samples)
        + 0.2 * np.sin(2 * np.pi * 0.17 * samples)
        + 0.1 * np.sin(2 * np.pi * 7.0 * samples)
    )
    quantized = (np.round(waveform / 0.02) * 0.02).astype(np.float32)
    _, quality, reasons = validate_ecg_signal(
        quantized,
        sample_rate_hz=80,
        minimum_hours=6,
        maximum_hours=12,
    )
    assert quality.value == "pass"
    assert not any("flat" in reason.lower() for reason in reasons)


def test_sustained_flatline_is_rejected() -> None:
    samples = np.arange(6 * 3600 * 80, dtype=float) / 80.0
    ecg = np.sin(2 * np.pi * 1.1 * samples).astype(np.float32)
    ecg[: int(ecg.size * 0.25)] = 0.0
    _, quality, reasons = validate_ecg_signal(
        ecg,
        sample_rate_hz=80,
        minimum_hours=6,
        maximum_hours=12,
    )
    assert quality.value == "fail"
    assert any("flatlined" in reason.lower() for reason in reasons)


def test_malformed_schema_is_rejected(tmp_path: Path) -> None:
    upload = tmp_path / "bad.csv.gz"
    with gzip.open(upload, "wt", encoding="utf-8") as handle:
        handle.write("name,ecg_mv\nAlice,0.1\n")
    with pytest.raises(InputValidationError, match="only"):
        read_ecg_csv_gz(
            upload, sample_rate_hz=100, minimum_hours=6, maximum_hours=12
        )


def test_short_recording_is_quality_failure(tmp_path: Path) -> None:
    upload = tmp_path / "short.csv.gz"
    with gzip.open(upload, "wt", encoding="utf-8") as handle:
        handle.write("ecg_mv\n0.1\n0.2\n")
    _, quality, reasons = read_ecg_csv_gz(
        upload, sample_rate_hz=100, minimum_hours=6, maximum_hours=12
    )
    assert quality.value == "fail"
    assert "shorter" in reasons[0]


def test_plain_csv_and_npy_inputs(tmp_path: Path) -> None:
    csv_path = tmp_path / "record.csv"
    csv_path.write_text("ecg_mv\n0.1\n0.2\n", encoding="utf-8")
    csv_signal, csv_rate = load_ecg_input(
        csv_path,
        sampling_rate_hz=100,
        ecg_channel=None,
        maximum_hours=12,
    )
    np.testing.assert_allclose(csv_signal, [0.1, 0.2])
    assert csv_rate == 100

    npy_path = tmp_path / "record.npy"
    np.save(npy_path, np.array([0.3, 0.4], dtype=np.float32))
    npy_signal, npy_rate = load_ecg_input(
        npy_path,
        sampling_rate_hz=125,
        ecg_channel=None,
        maximum_hours=12,
    )
    np.testing.assert_allclose(npy_signal, [0.3, 0.4])
    assert npy_rate == 125


def test_edf_input_detects_ecg_channel_and_units(tmp_path: Path) -> None:
    edf_path = tmp_path / "record.edf"
    signal = np.sin(np.linspace(0, 20, 1000)) * 1000.0
    signal_header = pyedflib.highlevel.make_signal_header(
        "ECG",
        dimension="uV",
        sample_frequency=100,
        physical_min=-1200,
        physical_max=1200,
    )
    pyedflib.highlevel.write_edf(
        str(edf_path),
        [signal],
        [signal_header],
        pyedflib.highlevel.make_header(),
    )
    values, rate = load_ecg_input(
        edf_path,
        sampling_rate_hz=None,
        ecg_channel=None,
        maximum_hours=12,
    )
    assert rate == 100
    assert np.max(np.abs(values)) == pytest.approx(1.0, abs=0.01)


def test_wfdb_zip_input_is_safely_decoded(tmp_path: Path) -> None:
    record_name = "record"
    signal = np.sin(np.linspace(0, 20, 1000)).reshape(-1, 1)
    wfdb.wrsamp(
        record_name,
        fs=100,
        units=["mV"],
        sig_name=["ECG"],
        p_signal=signal,
        write_dir=str(tmp_path),
    )
    archive_path = tmp_path / "record.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(tmp_path / "record.hea", "record.hea")
        archive.write(tmp_path / "record.dat", "record.dat")
    values, rate = load_ecg_input(
        archive_path,
        sampling_rate_hz=None,
        ecg_channel=None,
        maximum_hours=12,
    )
    assert rate == 100
    assert values.shape == (1000,)


def test_unknown_format_is_rejected() -> None:
    with pytest.raises(InputValidationError, match="Supported formats"):
        detect_upload_suffix("record.txt")
