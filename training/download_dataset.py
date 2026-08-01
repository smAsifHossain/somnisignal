from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path


BASE_URL = "https://physionet.org/files/apnea-ecg/1.0.0"
RECORDS = tuple(
    [f"a{index:02d}" for index in range(1, 21)]
    + [f"b{index:02d}" for index in range(1, 6)]
    + [f"c{index:02d}" for index in range(1, 11) if index != 6]
)


def download(url: str, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size > 0:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    print(f"Downloading {destination.name}", flush=True)
    urllib.request.urlretrieve(url, temporary)
    temporary.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("training/data/apnea-ecg"))
    parser.add_argument("--include-qrs", action="store_true")
    args = parser.parse_args()

    suffixes = ["hea", "dat", "apn"]
    if args.include_qrs:
        suffixes.append("qrs")
    for record in RECORDS:
        for suffix in suffixes:
            filename = f"{record}.{suffix}"
            download(f"{BASE_URL}/{filename}", args.output_dir / filename)


if __name__ == "__main__":
    main()
