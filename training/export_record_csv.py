from __future__ import annotations

import argparse
import gzip
from pathlib import Path

import numpy as np
import wfdb


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", help="WFDB record base path, without extension")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    record = wfdb.rdrecord(args.record)
    if record.p_signal is None or record.p_signal.shape[1] != 1:
        raise ValueError("Expected one physical ECG signal.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8", newline="") as handle:
        handle.write("ecg_mv\n")
        np.savetxt(handle, record.p_signal[:, 0], fmt="%.6g")
    print(
        f"Exported {record.sig_len} samples at {record.fs:g} Hz to {args.output}"
    )


if __name__ == "__main__":
    main()
