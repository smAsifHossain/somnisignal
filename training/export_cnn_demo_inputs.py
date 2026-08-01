"""Export allowlisted public PhysioNet RR sequences for API demo jobs."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


RR_SEQUENCE_LENGTH = 4 * 5 * 60


DEMO_RECORDS = ("a01", "b01", "c01")


def export_demo_inputs(cache_dir: Path, output_path: Path) -> None:
    records: dict[str, np.ndarray] = {}
    for record_id in DEMO_RECORDS:
        cache_path = cache_dir / "rr-cnn-gqrs-v1" / f"{record_id}.npz"
        cached = np.load(cache_path, allow_pickle=False)
        sequences = np.asarray(cached["sequences"], dtype=np.float32)
        if sequences.ndim != 2 or sequences.shape[1] != RR_SEQUENCE_LENGTH:
            raise RuntimeError(f"Invalid cached RR sequences for {record_id}.")
        if not np.isfinite(sequences).all():
            raise RuntimeError(f"Non-finite cached RR sequences for {record_id}.")
        records[record_id] = sequences

    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output_path, **records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=Path("training/cache"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/candidates/demo_rr_sequences.npz"),
    )
    args = parser.parse_args()
    export_demo_inputs(args.cache_dir, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
