from __future__ import annotations

import argparse
import gzip
import math
from pathlib import Path


def sample_value(index: int, sample_rate_hz: int) -> float:
    time_seconds = index / sample_rate_hz
    beat_phase = time_seconds % 1.0

    def pulse(center: float, width: float, amplitude: float) -> float:
        distance = (beat_phase - center) / width
        return amplitude * math.exp(-0.5 * distance * distance)

    baseline = 0.035 * math.sin(2.0 * math.pi * 0.22 * time_seconds)
    interference = (
        0.010 * math.sin(2.0 * math.pi * 17.3 * time_seconds)
        + 0.006 * math.sin(2.0 * math.pi * 23.7 * time_seconds)
    )
    return (
        baseline
        + interference
        + pulse(0.025, 0.012, -0.14)
        + pulse(0.050, 0.014, 1.10)
        + pulse(0.078, 0.016, -0.24)
        + pulse(0.300, 0.070, 0.20)
    )


def create_file(path: Path, *, hours: float, sample_rate_hz: int, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; use --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_count = int(hours * 3600 * sample_rate_hz)
    chunk_size = 20_000
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write("ecg_mv\n")
        for start in range(0, sample_count, chunk_size):
            stop = min(start + chunk_size, sample_count)
            rows = (f"{sample_value(index, sample_rate_hz):.6f}\n" for index in range(start, stop))
            handle.writelines(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a synthetic, non-patient ECG file for SomniSignal local upload testing."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("sample-data/synthetic-ecg-6h-100hz.csv.gz"),
    )
    parser.add_argument("--hours", type=float, default=6.0)
    parser.add_argument("--sampling-rate-hz", type=int, default=100)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not 6.0 <= args.hours <= 12.0:
        parser.error("--hours must be between 6 and 12")
    if not 80 <= args.sampling_rate_hz <= 250:
        parser.error("--sampling-rate-hz must be between 80 and 250")
    create_file(
        args.output,
        hours=args.hours,
        sample_rate_hz=args.sampling_rate_hz,
        force=args.force,
    )
    print(f"Created {args.output.resolve()}")
    print(f"Sampling rate: {args.sampling_rate_hz} Hz")
    print(f"Duration: {args.hours:g} hours")


if __name__ == "__main__":
    main()
