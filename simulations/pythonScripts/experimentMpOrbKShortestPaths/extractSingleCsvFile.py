#!/usr/bin/env python3
"""Extract CSV-R without merging MPTCP connection IDs or counting TCP bytes as goodput."""

import argparse
import csv
import json
import math
import os
import re
import sys
from pathlib import Path

import numpy as np

from generateExperimentMpOrbKShortestPathsIni import EXPERIMENT_DIR, MANIFEST_FILE
from parallelProcessing import run_parallel

CSV_DIR = EXPERIMENT_DIR / "csvs"
csv.field_size_limit(sys.maxsize)


def read_csv_file(path):
    vectors, scalars = {}, {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("module", ""), row.get("name", "").split(":")[0])
            if row.get("type") == "scalar":
                scalars[key] = float(row["value"])
            elif row.get("type") == "vector":
                times = np.fromstring(row.get("vectime", ""), sep=" ")
                values = np.fromstring(row.get("vecvalue", ""), sep=" ")
                if len(times) != len(values) or np.any(np.diff(times) < 0):
                    raise ValueError(f"Malformed vector {key} in {path}")
                if key in vectors:
                    raise ValueError(f"Duplicate vector {key}; export exactly one simulation run")
                vectors[key] = (times, values)
    return vectors, scalars


def sample_hold(times, values, grid, initial=math.nan):
    result = np.full(len(grid), initial, dtype=float)
    if len(times):
        indices = np.searchsorted(times, grid, side="right") - 1
        valid = indices >= 0
        result[valid] = values[indices[valid]]
    return result


def interval_rate_integral(times, values, start, end):
    """Goodput rates describe the interval ENDING at each timestamp."""
    if not len(times):
        return 0.0
    # The first sample begins at establishment, which is not exported here.
    # Only accept full measured intervals; the common window begins at 10s.
    left = times[:-1]
    right = times[1:]
    widths = np.maximum(0, np.minimum(right, end) - np.maximum(left, start))
    return float(np.sum(widths * values[1:]))


def rate_series(vectors, grid, start, end, bytes_received):
    total = np.zeros(len(grid))
    mean = 0.0
    for times, values in vectors:
        if len(times) and (not np.all(np.isfinite(values)) or np.any(values < 0)):
            raise ValueError("Invalid receiver goodput vector")
        mean += interval_rate_integral(times, values, start, end) / (end - start)
        # End-of-interval values for plotting (no interpolation through outages).
        if len(times):
            indices = np.searchsorted(times, grid, side="left")
            valid = (indices < len(times)) & (grid >= times[0])
            total[valid] += values[indices[valid]]
    if bytes_received > 0 and not vectors:
        raise ValueError("Receiver bytes were delivered but the goodput vector is missing")
    return mean / 1e6, total / 1e6


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def extract_config(config):
    name = config["config"]
    raw = CSV_DIR / "raw" / f"{name}.csv"
    vectors, scalars = read_csv_file(raw)
    destination = f'.userTerminal[{config["destination"]}].app[0]'
    source = f'.userTerminal[{config["source"]}]'
    receiver_scalars = [v for (module, metric), v in scalars.items()
                        if module.endswith(destination) and metric == "bytesRcvd"]
    if len(receiver_scalars) != 1:
        raise ValueError(f"{name}: expected exactly one receiver application bytesRcvd scalar")
    bytes_received = receiver_scalars[0]
    if not math.isfinite(bytes_received) or bytes_received < 0:
        raise ValueError(f"{name}: invalid receiver byte count")
    start, end = config["measurement_start"], config["measurement_end"]
    grid = np.arange(0, config["sim_time"], 1.0)
    goodput = [series for (module, metric), series in vectors.items()
               if destination + ".thread_" in module and metric == "goodput"]
    mean_goodput, goodput_series = rate_series(goodput, grid, start, end, bytes_received)
    late = any(len(t) and t[0] > start for t, _ in goodput)
    # Never report a deceptively precise steady-window mean after a late first
    # sample. Full-run goodput from the byte scalar remains exact and available.
    if late:
        mean_goodput = math.nan

    paths = []
    available = []
    series_available = []
    # Sample after each configurator update. These are catalog availability
    # samples, not proof of connection establishment or continuous forwarding.
    path_grid = np.arange(start + 0.000002, end, 0.1)
    for rank in range(1, config["k"] + 1):
        prefix = source + f".app[{rank}]"
        def get_metric(metric, sample_grid=path_grid):
            matches = [series for (module, m), series in vectors.items() if module.endswith(prefix) and m == metric]
            if len(matches) != 1 or not len(matches[0][0]):
                raise ValueError(f"{name}: missing route monitor rank {rank} / {metric}")
            times, _ = matches[0]
            if times[0] > start or times[-1] < end - 0.11:
                raise ValueError(f"{name}: route monitor does not cover the measurement window")
            return sample_hold(*matches[0], sample_grid)
        availability = get_metric("kPathAvailable")
        if np.any(~np.isfinite(availability)) or np.any((availability != 0) & (availability != 1)):
            raise ValueError(f"{name}: incomplete path availability samples")
        expected_rtt = get_metric("kPathExpectedRtt")
        valid = (availability == 1) & (expected_rtt >= 0)
        paths.append(dict(config=name, pair=config["pair"], k=config["k"], run=config["run"],
                          rank=rank, available_fraction=float(np.mean(availability)),
                          expected_rtt_ms=float(np.mean(expected_rtt[valid]) * 1000) if np.any(valid) else math.nan))
        available.append(availability)
        series_available.append(get_metric("kPathAvailable", grid + 0.000003))
    availability_sum = np.sum(available, axis=0)

    rtt_values = [v[(t >= start) & (t <= end)] for (module, metric), (t, v) in vectors.items()
                  if source + ".tcp." in module and metric == "rtt"]
    rtts = np.concatenate(rtt_values) if rtt_values else np.array([])
    rtts = rtts[np.isfinite(rtts) & (rtts > 0)]
    raw_stat = raw.stat()
    summary = dict(config, raw_stat=[raw_stat.st_size, raw_stat.st_mtime_ns], goodput_mbps=mean_goodput,
                   full_run_goodput_mbps=bytes_received * 8 / (config["sim_time"] - config["start"]) / 1e6,
                   bytes_received=bytes_received, late_goodput_start=late,
                   sender_rtt_ms=float(np.mean(rtts) * 1000) if len(rtts) else math.nan,
                   mean_available_paths=float(np.mean(availability_sum)),
                   all_k_available_pct=float(np.mean(availability_sum == config["k"]) * 100),
                   highest_rank_rtt_ms=paths[-1]["expected_rtt_ms"])
    out = CSV_DIR / "extracted" / name
    out.mkdir(parents=True, exist_ok=True)
    # Keep conn-IDs and thread IDs intact. Raw/extracted TCP throughput includes
    # transport retransmissions and must not be added to application goodput.
    for (module, metric), (times, values) in vectors.items():
        filename = re.sub(r"[^A-Za-z0-9_.\[\]-]", "_", f"{module}__{metric}") + ".csv"
        np.savetxt(out / filename, np.column_stack((times, values)), delimiter=",",
                   header="time,value", comments="", fmt="%.12g")
    write_csv(out / "paths.csv", list(paths[0]), paths)
    np.savetxt(out / "timeseries.csv", np.column_stack((grid, goodput_series,
               np.sum(series_available, axis=0))), delimiter=",",
               header="time,goodput_mbps,available_paths", comments="", fmt="%.12g")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary, paths


def extract_results(configs, cores=1):
    summaries, paths = [], []
    for summary, path_rows in run_parallel(extract_config, configs, cores):
        summaries.append(summary)
        paths.extend(path_rows)
    write_csv(CSV_DIR / "summary.csv", list(summaries[0]), summaries)
    write_csv(CSV_DIR / "path_summary.csv", list(paths[0]), paths)
    print(f"Extracted {len(summaries)} runs to {CSV_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Extract one named run, otherwise the entire matrix")
    parser.add_argument("--cores", type=int, default=int(os.environ.get("EXPERIMENT_CORES", "2")))
    args = parser.parse_args()
    configs = json.loads(MANIFEST_FILE.read_text())
    if args.config:
        configs = [c for c in configs if c["config"] == args.config]
    if args.cores < 1:
        parser.error("--cores must be positive")
    if not configs:
        parser.error("No matching configuration")
    extract_results(configs, cores=args.cores)
