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
    "retransmissionRate",
    "liaAlpha",
    "oliaEpsilon",
    "baliaAi",
    "baliaMd",
    "semiCoupledAlphaSubflowRate",
    "semiCoupledAlphaConnectionRate",
    "semiCoupledAlphaRateShare",
    "semiCoupledDeltaTargetShare",
    "semiCoupledDeltaRateShare",
    "semiCoupledDeltaAiShare",
    "queueLength",
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
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    values = np.fromstring(text, sep=" ")
    if values.size == 0 and "," in text:
        values = np.fromstring(text.replace(",", " "), sep=" ")
    return values if values.size else None


def vector_name(name: str) -> str:
    return name.split(":", 1)[0].strip()


def clean_module_name(name: str) -> str:
    return re.sub(r"\.thread_\d+", "", name)


def write_metric(out_root: Path, module_name: str, metric: str, times, values) -> bool:
    if times is None or values is None:
        return False
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    if times.size == 0 or values.size == 0:
        return False
    count = min(times.size, values.size)
    out_dir = out_root / clean_module_name(module_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"time": times[:count], metric: values[:count]}).to_csv(
        out_dir / f"{metric}.csv", index=False
    )
    return True


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: extractSingleCsvFile.py <scavetool_csv> <protocol> <run>")
        return 2

    csv_path = Path(sys.argv[1])
    protocol = sys.argv[2]
    run = sys.argv[3]
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
    required = {"module", "name"}
    if not required.issubset(results.columns):
        print(f"missing required columns: {sorted(required - set(results.columns))}")
        return 1

    vectors = results
    if "type" in results.columns:
        vectors = results[results["type"].astype(str).str.strip().str.lower().eq("vector")]

    out_root = (
        Path(__file__).resolve().parents[2]
        / "experiments"
        / "experiment3"
        / "csvs"
        / protocol
        / f"run{run}"
    )
    written = 0
    if {"vectime", "vecvalue"}.issubset(vectors.columns):
        for _, row in vectors.iterrows():
            metric = vector_name(str(row["name"]))
            if metric in VECTORS_TO_EXTRACT and write_metric(
                out_root, str(row["module"]), metric, row["vectime"], row["vecvalue"]
            ):
                written += 1
    elif {"time", "value"}.issubset(vectors.columns):
        for (module_name, name), group in vectors.groupby(["module", "name"], sort=False):
            metric = vector_name(str(name))
            if metric not in VECTORS_TO_EXTRACT:
                continue
            times = pd.to_numeric(group["time"], errors="coerce").to_numpy()
            values = pd.to_numeric(group["value"], errors="coerce").to_numpy()
            mask = np.isfinite(times) & np.isfinite(values)
            if write_metric(out_root, str(module_name), metric, times[mask], values[mask]):
                written += 1
    else:
        print("unsupported vector CSV layout: expected vectime/vecvalue or time/value")
        print("columns:", ", ".join(str(column) for column in results.columns))
        return 1

    print(f"wrote {written} vector CSV files under {out_root}")
    if written == 0:
        names = sorted({vector_name(str(name)) for name in vectors["name"].dropna()})
        print("available vector names:", ", ".join(names[:60]))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
