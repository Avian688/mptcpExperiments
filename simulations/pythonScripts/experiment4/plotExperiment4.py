#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

MSS_BYTES = 1448
PATH_CAPACITY_MBPS = 20.0
COMPETITION_START = 40.0
COMPETITION_END = 80.0
BASELINE_START = 20.0
CONTESTED_START = 60.0
FINAL_WINDOW_SECONDS = 60.0
RECOVERY_FRACTION = 0.9
SUSTAIN_SECONDS = 5.0
SAMPLE_SECONDS = 0.5
DEFAULT_RUNS = [1, 2, 3, 4, 5]
BACKGROUND_FLOW_COUNT = 5

PROTOCOLS = [
    ("lia", "LIA"),
    ("olia", "OLIA"),
    ("balia", "BALIA"),
    ("mporb", "MPORB Uncoupled"),
    ("mporb_alpha", "MPORB Alpha"),
    ("mporb_delta", "MPORB Delta"),
]


@dataclass
class Bundle:
    run: int
    protocol: str
    label: str
    goodput: pd.Series
    path1: pd.Series
    path2: pd.Series
    cwnd1: pd.Series
    cwnd2: pd.Series
    background_goodput: list[pd.Series]


def read_series(path: Path, column: str) -> pd.Series | None:
    if not path.exists():
        return None
    frame = pd.read_csv(path)
    if "time" not in frame.columns or column not in frame.columns:
        return None
    series = pd.Series(frame[column].to_numpy(dtype=float), index=frame["time"].to_numpy(dtype=float))
    return series[~series.index.duplicated(keep="last")].sort_index()


def conn_id(path: Path) -> int:
    match = re.search(r"\.conn-(\d+)$", path.parent.name)
    return int(match.group(1)) if match else -1


def resample(series: pd.Series, grid: np.ndarray) -> pd.Series:
    if series.empty:
        return pd.Series(np.zeros_like(grid), index=grid)
    return series.reindex(series.index.union(grid)).sort_index().ffill().reindex(grid).fillna(0)


def load_connection_series(
    run_root: Path, module_prefix: str, metric: str, count: int | None = None
) -> list[pd.Series]:
    paths = sorted(
        (
            path
            for path in run_root.glob(f"*/{metric}.csv")
            if path.parent.name.startswith(module_prefix)
        ),
        key=conn_id,
    )
    series = [item for path in paths if (item := read_series(path, metric)) is not None and not item.empty]
    return series[-count:] if count is not None else series


def path2_index(paths: list[pd.Series]) -> int:
    contested_grid = np.arange(CONTESTED_START, COMPETITION_END, SAMPLE_SECONDS)
    means = [float(resample(path, contested_grid).mean()) for path in paths]
    return int(np.argmin(means))


def load_bundle(csv_root: Path, protocol: str, label: str, run: int) -> Bundle | None:
    run_root = csv_root / protocol / f"run{run}"
    goodput = read_series(
        run_root / "baliaresponsiveness.server[0].app[0]" / "goodput.csv", "goodput"
    )
    throughput = load_connection_series(
        run_root, "baliaresponsiveness.server[0].tcp.conn-", "throughput", 2
    )
    congestion_windows = load_connection_series(
        run_root, "baliaresponsiveness.client[0].tcp.conn-", "cwnd", 2
    )
    background_goodput = [
        item
        for path in sorted(run_root.glob("*/goodput.csv"))
        if path.parent.name.startswith("baliaresponsiveness.backgroundServer[")
        and (item := read_series(path, "goodput")) is not None
        and not item.empty
    ]

    if (
        goodput is None
        or len(throughput) != 2
        or len(congestion_windows) != 2
        or len(background_goodput) != BACKGROUND_FLOW_COUNT
    ):
        print(
            f"warning: incomplete {label} run{run}: goodput={goodput is not None}, "
            f"throughput subflows={len(throughput)}, cwnd subflows={len(congestion_windows)}, "
            f"background flows={len(background_goodput)}"
        )
        return None

    contested_grid = np.arange(CONTESTED_START, COMPETITION_END, SAMPLE_SECONDS)
    inactive_background = [
        index
        for index, series in enumerate(background_goodput)
        if float(resample(series, contested_grid).mean()) <= 0.0
    ]
    if inactive_background:
        print(
            f"warning: invalid {label} run{run}: no contested-window delivery from "
            f"background flow(s) {inactive_background}"
        )
        return None

    suppressed = path2_index(throughput)
    other = 1 - suppressed
    return Bundle(
        run,
        protocol,
        label,
        goodput,
        throughput[other],
        throughput[suppressed],
        congestion_windows[other],
        congestion_windows[suppressed],
        background_goodput,
    )


def series_end(bundle: Bundle) -> float:
    return max(
        float(series.index.max())
        for series in (bundle.goodput, bundle.path1, bundle.path2, bundle.cwnd1, bundle.cwnd2)
    )


def mean_value(series: pd.Series, start: float, end: float, divisor: float = 1.0) -> float:
    grid = np.arange(start, end, SAMPLE_SECONDS)
    if grid.size == 0:
        return np.nan
    return float(resample(series, grid).mean() / divisor)


def background_values(bundle: Bundle, grid: np.ndarray) -> np.ndarray:
    values = np.zeros_like(grid, dtype=float)
    for series in bundle.background_goodput:
        values += resample(series, grid).to_numpy(dtype=float)
    values[(grid < COMPETITION_START) | (grid >= COMPETITION_END)] = 0.0
    return values


def recovery_metrics(
    series: pd.Series, baseline: float, start: float, end: float, divisor: float
) -> tuple[float, int, float]:
    grid = np.arange(start, end + SAMPLE_SECONDS, SAMPLE_SECONDS)
    values = resample(series, grid) / divisor
    threshold = RECOVERY_FRACTION * baseline
    sustain_samples = max(1, int(round(SUSTAIN_SECONDS / SAMPLE_SECONDS)))
    sustained = values.rolling(window=sustain_samples, min_periods=sustain_samples).mean()
    recovered = sustained[sustained >= threshold]
    recovery_time = float(recovered.index[0] - start) if not recovered.empty else np.nan

    deficit_end = float(recovered.index[0]) if not recovered.empty else end
    deficit_grid = grid[grid <= deficit_end]
    deficit_values = values.reindex(deficit_grid).to_numpy(dtype=float)
    deficit = float(np.trapezoid(np.maximum(baseline - deficit_values, 0.0), deficit_grid))
    return recovery_time, int(not recovered.empty), deficit


def build_run_summary(bundle: Bundle) -> dict[str, float | int | str]:
    end = series_end(bundle)
    final_start = max(COMPETITION_END, end - FINAL_WINDOW_SECONDS)
    cwnd_baseline = mean_value(bundle.cwnd2, BASELINE_START, COMPETITION_START, MSS_BYTES)
    rate_baseline = mean_value(bundle.path2, BASELINE_START, COMPETITION_START, 1e6)
    cwnd_recovery, cwnd_success, cwnd_deficit = recovery_metrics(
        bundle.cwnd2, cwnd_baseline, COMPETITION_END, end, MSS_BYTES
    )
    rate_recovery, rate_success, rate_deficit = recovery_metrics(
        bundle.path2, rate_baseline, COMPETITION_END, end, 1e6
    )
    contested_grid = np.arange(CONTESTED_START, COMPETITION_END, SAMPLE_SECONDS)

    return {
        "run": bundle.run,
        "protocol": bundle.protocol,
        "label": bundle.label,
        "path2_baseline_mbps": rate_baseline,
        "path2_contested_mbps": mean_value(bundle.path2, CONTESTED_START, COMPETITION_END, 1e6),
        "path2_final_mbps": mean_value(bundle.path2, final_start, end, 1e6),
        "path2_cwnd_baseline_packets": cwnd_baseline,
        "path2_cwnd_contested_packets": mean_value(
            bundle.cwnd2, CONTESTED_START, COMPETITION_END, MSS_BYTES
        ),
        "path2_cwnd_final_packets": mean_value(bundle.cwnd2, final_start, end, MSS_BYTES),
        "background_contested_mbps": float(background_values(bundle, contested_grid).mean() / 1e6),
        "final_goodput_mbps": mean_value(bundle.goodput, final_start, end, 1e6),
        "cwnd_recovery_time_s": cwnd_recovery,
        "cwnd_recovery_success": cwnd_success,
        "cwnd_recovery_deficit_packet_seconds": cwnd_deficit,
        "throughput_recovery_time_s": rate_recovery,
        "throughput_recovery_success": rate_success,
        "throughput_recovery_deficit_mbit": rate_deficit,
    }


def aggregate_summary(run_summary: pd.DataFrame) -> pd.DataFrame:
    numeric = [
        column
        for column in run_summary.select_dtypes(include=[np.number]).columns
        if column != "run"
    ]
    rows = []
    for (protocol, label), group in run_summary.groupby(["protocol", "label"], sort=False):
        row: dict[str, float | int | str] = {
            "protocol": protocol,
            "label": label,
            "run_count": int(group["run"].nunique()),
        }
        for column in numeric:
            values = group[column].dropna().astype(float)
            row[column] = float(values.mean()) if not values.empty else np.nan
            row[f"{column}_std"] = float(values.std(ddof=0)) if not values.empty else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def errors(summary: pd.DataFrame, column: str) -> np.ndarray:
    return summary[f"{column}_std"].fillna(0).to_numpy(dtype=float)


def save_responsiveness_plot(summary: pd.DataFrame, out_dir: Path) -> None:
    labels = summary["label"].tolist()
    x = np.arange(len(summary))
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6))

    column = "cwnd_recovery_time_s"
    axes[0].bar(x, summary[column], yerr=errors(summary, column), capsize=3)
    axes[0].set_title("Recovery Time")
    axes[0].set_ylabel("Seconds")

    column = "cwnd_recovery_deficit_packet_seconds"
    axes[1].bar(x, summary[column], yerr=errors(summary, column), capsize=3)
    axes[1].set_title("Recovery Deficit")
    axes[1].set_ylabel("Packet-seconds")

    for ax in axes:
        ax.set_xticks(x, labels, rotation=18, ha="right")
        ax.grid(True, axis="y", alpha=0.3)
    fig.suptitle("Responsiveness")
    fig.tight_layout()
    fig.savefig(out_dir / "responsiveness.pdf")
    plt.close(fig)


def band(
    ax, grid: np.ndarray, series: list[pd.Series], label: str, divisor: float = 1e6
) -> None:
    matrix = np.vstack(
        [resample(item, grid).to_numpy(dtype=float) / divisor for item in series]
    )
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    ax.plot(grid, mean, label=label)
    ax.fill_between(grid, np.maximum(mean - std, 0), mean + std, alpha=0.18)


def background_band(ax, grid: np.ndarray, bundles: list[Bundle]) -> None:
    matrix = np.vstack([background_values(bundle, grid) / 1e6 for bundle in bundles])
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    ax.plot(grid, mean, linestyle="--", label="Competing flows")
    ax.fill_between(grid, np.maximum(mean - std, 0), mean + std, alpha=0.12)


def mark_competition(ax) -> None:
    ax.axvspan(COMPETITION_START, COMPETITION_END, color="grey", alpha=0.12)
    ax.axvline(COMPETITION_START, color="grey", linestyle=":", linewidth=1)
    ax.axvline(COMPETITION_END, color="grey", linestyle=":", linewidth=1)
    ax.set_xlabel("Time (s)")
    ax.grid(True, alpha=0.3)


def save_main_connection_goodput(
    grouped: dict[str, list[Bundle]], out_dir: Path
) -> None:
    bundles = [bundle for group in grouped.values() for bundle in group]
    if not bundles:
        return
    end = max(series_end(bundle) for bundle in bundles)
    grid = np.arange(0.0, end + SAMPLE_SECONDS, SAMPLE_SECONDS)
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    for protocol, label in PROTOCOLS:
        group = grouped.get(protocol, [])
        if group:
            band(ax, grid, [bundle.goodput for bundle in group], label)
    ax.axhline(
        2 * PATH_CAPACITY_MBPS,
        color="black",
        linestyle="--",
        linewidth=1,
        label="Total capacity",
    )
    ax.set_title("Main Connection Goodput")
    ax.set_ylabel("Mbps")
    ax.legend(fontsize=8)
    mark_competition(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "main_connection_goodput.pdf")
    plt.close(fig)


def save_individual_cwnd_plot(bundle: Bundle, out_root: Path) -> None:
    out_dir = out_root / "by_protocol" / bundle.protocol / "runs" / f"run{bundle.run}"
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    ax.step(
        bundle.cwnd1.index,
        bundle.cwnd1.to_numpy(dtype=float) / MSS_BYTES,
        where="post",
        label="Path 1",
    )
    ax.step(
        bundle.cwnd2.index,
        bundle.cwnd2.to_numpy(dtype=float) / MSS_BYTES,
        where="post",
        label="Path 2",
    )
    ax.set_title(f"{bundle.label} Run {bundle.run}: Subflow cwnd")
    ax.set_ylabel("Packets")
    ax.legend()
    mark_competition(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "subflow_cwnd.pdf")
    plt.close(fig)


def save_protocol_plot(protocol: str, label: str, bundles: list[Bundle], out_root: Path) -> None:
    out_dir = out_root / "by_protocol" / protocol
    out_dir.mkdir(parents=True, exist_ok=True)
    end = max(series_end(bundle) for bundle in bundles)
    grid = np.arange(0.0, end + SAMPLE_SECONDS, SAMPLE_SECONDS)

    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.5))
    band(axes[0], grid, [bundle.path1 for bundle in bundles], "Path 1")
    band(axes[0], grid, [bundle.path2 for bundle in bundles], "Path 2")
    background_band(axes[0], grid, bundles)
    axes[0].axhline(
        PATH_CAPACITY_MBPS, color="black", linestyle="--", linewidth=1, label="Path capacity"
    )
    axes[0].set_title("Throughput")
    axes[0].set_ylabel("Mbps")
    axes[0].legend()

    band(axes[1], grid, [bundle.cwnd1 for bundle in bundles], "Path 1", MSS_BYTES)
    band(axes[1], grid, [bundle.cwnd2 for bundle in bundles], "Path 2", MSS_BYTES)
    axes[1].set_title("Congestion Window")
    axes[1].set_ylabel("Packets")
    axes[1].legend()

    band(axes[2], grid, [bundle.goodput for bundle in bundles], "Aggregate")
    axes[2].axhline(
        2 * PATH_CAPACITY_MBPS,
        color="black",
        linestyle="--",
        linewidth=1,
        label="Total capacity",
    )
    axes[2].set_title("Goodput")
    axes[2].set_ylabel("Mbps")
    axes[2].legend()

    for ax in axes:
        mark_competition(ax)
    fig.suptitle(label)
    fig.tight_layout()
    fig.savefig(out_dir / "responsiveness.pdf")
    plt.close(fig)


def selected_runs(args: argparse.Namespace) -> list[int]:
    if args.run is not None:
        return [args.run]
    return sorted(set(args.runs)) if args.runs else DEFAULT_RUNS


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot mptcpExperiments experiment 4.")
    parser.add_argument("--run", type=int)
    parser.add_argument("--runs", nargs="*", type=int)
    args = parser.parse_args()

    sim_root = Path(__file__).resolve().parents[2]
    csv_root = sim_root / "experiments" / "experiment4" / "csvs"
    out_dir = sim_root / "plots" / "experiment4"
    shutil.rmtree(out_dir, ignore_errors=True)
    aggregate_dir = out_dir / "aggregate"
    aggregate_dir.mkdir(parents=True, exist_ok=True)

    bundles = [
        bundle
        for run in selected_runs(args)
        for protocol, label in PROTOCOLS
        if (bundle := load_bundle(csv_root, protocol, label, run)) is not None
    ]
    if not bundles:
        print(f"no extracted CSV data found under {csv_root}")
        return 1

    run_summary = pd.DataFrame(build_run_summary(bundle) for bundle in bundles)
    summary = aggregate_summary(run_summary)
    run_summary.to_csv(out_dir / "summary_runs.csv", index=False)
    summary.to_csv(out_dir / "summary.csv", index=False)
    save_responsiveness_plot(summary, aggregate_dir)

    grouped: dict[str, list[Bundle]] = defaultdict(list)
    for bundle in bundles:
        grouped[bundle.protocol].append(bundle)
    save_main_connection_goodput(grouped, aggregate_dir)
    for protocol, label in PROTOCOLS:
        if protocol in grouped:
            save_protocol_plot(protocol, label, grouped[protocol], out_dir)
    for bundle in bundles:
        save_individual_cwnd_plot(bundle, out_dir)

    print(f"wrote experiment 4 plots under {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
