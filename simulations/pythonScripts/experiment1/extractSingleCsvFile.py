#!/usr/bin/env python3

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

VECTORS_TO_EXTRACT = {
    "goodput",
    "throughput",
    "cwnd",
    "rtt",
    "srtt",
    "mbytesInFlight",
    "retransmissionRate",
    "queueLength",
    "queueBitLength",
    "queueingTime",
}


def parse_if_number(value: str):
    try:
        return float(value)
    except Exception:
        if value == "true":
            return True
        if value == "false":
            return False
        return value if value else None


def parse_ndarray(value: str):
    return np.fromstring(value, sep=" ") if value else None


def vector_name(name: str) -> str:
    return name.split(":", 1)[0]


def clean_module_name(name: str) -> str:
    # Server threads get unique suffixes; remove them so app-level goodput paths are stable.
    return re.sub(r"\.thread_\d+", "", name)


def main() -> int:
    if len(sys.argv) != 5:
        print("usage: extractSingleCsvFile.py <scavetool_csv> <protocol> <scheduler> <run>")
        return 2

    csv_path = Path(sys.argv[1])
    protocol = sys.argv[2]
    scheduler = sys.argv[3]
    run = sys.argv[4]

    if not csv_path.exists():
        print(f"missing input CSV: {csv_path}")
        return 1

    results = pd.read_csv(
        csv_path,
        converters={
            "attrvalue": parse_if_number,
            "binedges": parse_ndarray,
            "binvalues": parse_ndarray,
            "vectime": parse_ndarray,
            "vecvalue": parse_ndarray,
        },
    )

    vectors = results[results.type == "vector"]
    out_root = (
        Path(__file__).resolve().parents[2]
        / "paperExperiments"
        / "experiment1"
        / "csvs"
        / protocol
        / scheduler
        / f"run{run}"
    )

    written = 0
    for _, row in vectors.iterrows():
        metric = vector_name(str(row["name"]))
        if metric not in VECTORS_TO_EXTRACT:
            continue

        values = row["vecvalue"]
        times = row["vectime"]
        if values is None or times is None:
            continue

        module_name = clean_module_name(str(row["module"]))
        out_dir = out_root / module_name
        out_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"time": times, metric: values}).to_csv(out_dir / f"{metric}.csv", index=False)
        written += 1

    print(f"wrote {written} vector CSV files under {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
