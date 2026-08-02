from __future__ import annotations

import csv
import gzip
import shutil
import tempfile
import zipfile
from array import array
from pathlib import Path, PurePosixPath

import numpy as np
import pyedflib
import wfdb


SUPPORTED_UPLOAD_SUFFIXES = (".csv.gz", ".csv", ".edf", ".bdf", ".npy", ".zip")
SAMPLING_RATE_REQUIRED_SUFFIXES = {".csv.gz", ".csv", ".npy"}
MAX_WFDB_UNCOMPRESSED_BYTES = 96 * 1024 * 1024
MAX_WFDB_MEMBERS = 16


class InputValidationError(ValueError):
    pass


def detect_upload_suffix(filename: str) -> str:
    lowered = filename.strip().lower()
    for suffix in SUPPORTED_UPLOAD_SUFFIXES:
        if lowered.endswith(suffix):
            return suffix
    raise InputValidationError(
        "Supported formats are CSV, CSV.GZ, EDF/BDF, NPY, and WFDB ZIP."
    )


def _validated_rate(value: float | int | None) -> int:
    if value is None or not np.isfinite(value):
        raise InputValidationError("A valid ECG sampling rate is required.")
    rounded = int(round(float(value)))
    if abs(float(value) - rounded) > 0.01 or not 80 <= rounded <= 250:
        raise InputValidationError("ECG sampling rate must be an integer from 80 to 250 Hz.")
    return rounded


def _to_millivolts(values: np.ndarray, unit: str | None, *, metadata_required: bool) -> np.ndarray:
    normalized = (unit or "").strip().lower().replace("µ", "u").replace("μ", "u")
    factors = {
        "mv": 1.0,
        "millivolt": 1.0,
        "millivolts": 1.0,
        "uv": 0.001,
        "microvolt": 0.001,
        "microvolts": 0.001,
        "v": 1000.0,
        "volt": 1000.0,
        "volts": 1000.0,
    }
    if not normalized and not metadata_required:
        return np.asarray(values, dtype=np.float32)
    if normalized not in factors:
        raise InputValidationError("The ECG channel must declare units as V, mV, or uV.")
    return np.asarray(values, dtype=np.float32) * factors[normalized]


def _select_channel(labels: list[str], requested: str | None) -> int:
    cleaned = [str(label).strip() for label in labels]
    if requested and requested.strip():
        choice = requested.strip()
        if choice.isdigit():
            index = int(choice)
            if 0 <= index < len(cleaned):
                return index
        exact = [index for index, label in enumerate(cleaned) if label.lower() == choice.lower()]
        if len(exact) == 1:
            return exact[0]
        raise InputValidationError("The requested ECG channel was not found.")

    candidates = [
        index
        for index, label in enumerate(cleaned)
        if "ecg" in label.lower() or "ekg" in label.lower()
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates and len(cleaned) == 1:
        return 0
    if len(candidates) > 1:
        raise InputValidationError("Multiple ECG channels were found; select one channel.")
    raise InputValidationError("No ECG channel could be identified in the uploaded recording.")


def _load_csv(
    path: Path,
    *,
    compressed: bool,
    sample_rate_hz: int | None,
    maximum_hours: float,
) -> tuple[np.ndarray, int]:
    rate = _validated_rate(sample_rate_hz)
    maximum_samples = int(maximum_hours * 3600 * rate)
    values = array("f")
    opener = gzip.open if compressed else open
    try:
        with opener(path, mode="rt", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            if next(reader, None) != ["ecg_mv"]:
                raise InputValidationError("CSV must contain only the 'ecg_mv' column.")
            for row_number, row in enumerate(reader, start=2):
                if len(row) != 1:
                    raise InputValidationError("Every CSV row must contain one ECG value.")
                try:
                    values.append(float(row[0]))
                except ValueError as exc:
                    raise InputValidationError(
                        f"Invalid ECG value at row {row_number}."
                    ) from exc
                if len(values) > maximum_samples:
                    raise InputValidationError("Recording exceeds the 12-hour limit.")
    except (gzip.BadGzipFile, EOFError, UnicodeDecodeError, OSError) as exc:
        raise InputValidationError("The CSV upload could not be read safely.") from exc
    return np.asarray(values, dtype=np.float32), rate


def _load_npy(path: Path, sample_rate_hz: int | None) -> tuple[np.ndarray, int]:
    rate = _validated_rate(sample_rate_hz)
    try:
        values = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise InputValidationError("The NPY upload could not be read safely.") from exc
    if values.ndim == 2 and 1 in values.shape:
        values = values.reshape(-1)
    if values.ndim != 1 or not np.issubdtype(values.dtype, np.number):
        raise InputValidationError("NPY input must contain one numeric ECG vector.")
    return _to_millivolts(values, None, metadata_required=False), rate


def _load_edf(
    path: Path,
    *,
    requested_channel: str | None,
    maximum_hours: float,
) -> tuple[np.ndarray, int]:
    try:
        reader = pyedflib.EdfReader(str(path))
    except (OSError, RuntimeError) as exc:
        raise InputValidationError("The EDF/BDF upload could not be opened safely.") from exc
    try:
        labels = list(reader.getSignalLabels())
        channel = _select_channel(labels, requested_channel)
        rate = _validated_rate(reader.getSampleFrequency(channel))
        sample_counts = reader.getNSamples()
        if int(sample_counts[channel]) > int(maximum_hours * 3600 * rate):
            raise InputValidationError("Recording exceeds the 12-hour limit.")
        unit = reader.getPhysicalDimension(channel)
        values = reader.readSignal(channel, digital=False)
    except (IndexError, OSError, RuntimeError) as exc:
        raise InputValidationError("The EDF/BDF ECG channel could not be read safely.") from exc
    finally:
        reader.close()
    return _to_millivolts(values, unit, metadata_required=True), rate


def _load_wfdb_zip(
    path: Path,
    *,
    requested_channel: str | None,
) -> tuple[np.ndarray, int]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise InputValidationError("The WFDB ZIP upload could not be opened safely.") from exc
    with archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        if not members or len(members) > MAX_WFDB_MEMBERS:
            raise InputValidationError("WFDB ZIP contains an invalid number of files.")
        if sum(member.file_size for member in members) > MAX_WFDB_UNCOMPRESSED_BYTES:
            raise InputValidationError("WFDB ZIP expands beyond the safe processing limit.")
        safe_members: list[zipfile.ZipInfo] = []
        for member in members:
            name = PurePosixPath(member.filename)
            if len(name.parts) != 1 or name.name != member.filename:
                raise InputValidationError("WFDB ZIP files must be stored at the archive root.")
            if name.suffix.lower() not in {".hea", ".dat"}:
                raise InputValidationError("WFDB ZIP may contain only .hea and .dat files.")
            safe_members.append(member)
        headers = [member for member in safe_members if member.filename.lower().endswith(".hea")]
        if len(headers) != 1:
            raise InputValidationError("WFDB ZIP must contain exactly one header file.")

        with tempfile.TemporaryDirectory(prefix="wfdb-", dir=path.parent) as directory:
            extraction_root = Path(directory)
            for member in safe_members:
                destination = extraction_root / member.filename
                with archive.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
            record_path = extraction_root / Path(headers[0].filename).stem
            try:
                record = wfdb.rdrecord(str(record_path))
            except (OSError, ValueError) as exc:
                raise InputValidationError("The WFDB record could not be decoded safely.") from exc
            if record.p_signal is None:
                raise InputValidationError("WFDB record does not contain a physical ECG signal.")
            channel = _select_channel(list(record.sig_name or []), requested_channel)
            rate = _validated_rate(record.fs)
            units = list(record.units or [])
            unit = units[channel] if channel < len(units) else None
            values = np.asarray(record.p_signal[:, channel])
    return _to_millivolts(values, unit, metadata_required=True), rate


def load_ecg_input(
    path: Path,
    *,
    sampling_rate_hz: int | None,
    ecg_channel: str | None,
    maximum_hours: float,
) -> tuple[np.ndarray, int]:
    suffix = detect_upload_suffix(path.name)
    if suffix == ".csv.gz":
        return _load_csv(
            path,
            compressed=True,
            sample_rate_hz=sampling_rate_hz,
            maximum_hours=maximum_hours,
        )
    if suffix == ".csv":
        return _load_csv(
            path,
            compressed=False,
            sample_rate_hz=sampling_rate_hz,
            maximum_hours=maximum_hours,
        )
    if suffix == ".npy":
        return _load_npy(path, sampling_rate_hz)
    if suffix in {".edf", ".bdf"}:
        return _load_edf(
            path, requested_channel=ecg_channel, maximum_hours=maximum_hours
        )
    if suffix == ".zip":
        return _load_wfdb_zip(path, requested_channel=ecg_channel)
    raise InputValidationError("Unsupported ECG input format.")
