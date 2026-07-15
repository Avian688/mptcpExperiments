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

PROTOCOLS = [
    ("lia", "LIA"),
    ("olia", "OLIA"),
    ("balia", "BALIA"),
    ("mporb_alpha", "MPORB Alpha"),
    ("mporb_delta", "MPORB Delta"),
]
MSS_BYTES = 1448
RTT_SECONDS = 0.1
X_CAPACITY_MBPS = 90.0
T_CAPACITY_MBPS = 120.0
IDEAL_PROBE_MBPS = MSS_BYTES * 8 / RTT_SECONDS / 1e6
IDEAL_AGGREGATE_MBPS = X_CAPACITY_MBPS + T_CAPACITY_MBPS - IDEAL_PROBE_MBPS
DEFAULT_RUNS = [1, 2, 3, 4, 5]
QUEUE_MODULES = {
    "X": "oliapareto.xIngress.ppp[0].queue",
    "T": "oliapareto.tIngress.ppp[0].queue",
}


@dataclass
class Bundle:
    run: int
    protocol: str
    label: str
    goodput: dict[int, pd.Series]
    subflows: dict[int, list[pd.Series]]
    queues: dict[str, pd.Series]


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


def load_subflows(run_root: Path, user: int) -> list[pd.Series]:
    prefix = f"oliapareto.server[{user}].tcp.conn-"
    paths = [
        path
        for path in run_root.glob("*/throughput.csv")
        if path.parent.name.startswith(prefix)
    ]
    series = [
        item
        for path in sorted(paths, key=conn_id)
        if (item := read_series(path, "throughput")) is not None and not item.empty
    ]
    return series[-2:]


def load_bundle(csv_root: Path, protocol: str, label: str, run: int) -> Bundle | None:
    run_root = csv_root / protocol / f"run{run}"
    goodput: dict[int, pd.Series] = {}
    subflows: dict[int, list[pd.Series]] = {}
    for user in (0, 1):
        app = read_series(run_root / f"oliapareto.server[{user}].app[0]" / "goodput.csv", "goodput")
        paths = load_subflows(run_root, user)
        if app is None or len(paths) != 2:
            print(f"warning: incomplete {label} run{run} user {user}: goodput={app is not None}, subflows={len(paths)}")
            return None
        goodput[user] = app
        subflows[user] = paths

    queues: dict[str, pd.Series] = {}
    for name, module in QUEUE_MODULES.items():
        queue = read_series(run_root / module / "queueLength.csv", "queueLength")
        if queue is None:
            print(f"warning: missing {label} run{run} queue {name}")
            return None
        queues[name] = queue
    return Bundle(run, protocol, label, goodput, subflows, queues)


def resample(series: pd.Series, grid: np.ndarray) -> pd.Series:
    if series.empty:
        return pd.Series(np.zeros_like(grid), index=grid)
    return series.reindex(series.index.union(grid)).sort_index().ffill().reindex(grid).fillna(0)


def common_grid(bundles: list[Bundle]) -> np.ndarray:
    series: list[pd.Series] = []
    for bundle in bundles:
        series.extend(bundle.goodput.values())
        series.extend(bundle.queues.values())
        for paths in bundle.subflows.values():
            series.extend(paths)
    if not series:
        return np.asarray([])
    end = max(float(item.index.max()) for item in series if not item.empty)
    return np.arange(0.0, end + 0.5, 0.5)


def mean_mbps(series: pd.Series, grid: np.ndarray) -> float:
    return float(resample(series, grid).mean() / 1e6)


def build_run_summary(bundle: Bundle, analysis_start: float) -> dict[str, float | int | str]:
    grid = common_grid([bundle])
    grid = grid[grid >= analysis_start]
    if len(grid) == 0:
        return {}

    blue = mean_mbps(bundle.goodput[0], grid)
    red = mean_mbps(bundle.goodput[1], grid)
    x1 = mean_mbps(bundle.subflows[0][0], grid)
    x2 = mean_mbps(bundle.subflows[0][1], grid)
    y1 = mean_mbps(bundle.subflows[1][0], grid)
    y2 = mean_mbps(bundle.subflows[1][1], grid)
    aggregate = blue + red
    return {
        "run": bundle.run,
        "protocol": bundle.protocol,
        "label": bundle.label,
        "analysis_start_time_s": analysis_start,
        "analysis_end_time_s": float(grid.max()),
        "blue_goodput_mbps": blue,
        "red_goodput_mbps": red,
        "aggregate_goodput_mbps": aggregate,
        "aggregate_efficiency": aggregate / IDEAL_AGGREGATE_MBPS,
        "aggregate_loss_mbps": max(IDEAL_AGGREGATE_MBPS - aggregate, 0.0),
        "blue_x1_mbps": x1,
        "blue_x2_mbps": x2,
        "red_y1_mbps": y1,
        "red_y2_mbps": y2,
        "red_y1_excess_mbps": max(y1 - IDEAL_PROBE_MBPS, 0.0),
        "x_load_mbps": x1 + y1,
        "t_load_mbps": x2 + y1 + y2,
        "x_queue_packets": float(resample(bundle.queues["X"], grid).mean()),
        "t_queue_packets": float(resample(bundle.queues["T"], grid).mean()),
    }


def aggregate_summary(run_summary: pd.DataFrame) -> pd.DataFrame:
    numeric = [column for column in run_summary.select_dtypes(include=[np.number]).columns if column != "run"]
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
    return summary[f"{column}_std"].to_numpy(dtype=float)


def save_pareto_plot(summary: pd.DataFrame, out_dir: Path) -> None:
    labels = summary["label"].tolist()
    x = np.arange(len(summary))
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6))

    column = "aggregate_goodput_mbps"
    axes[0].bar(x, summary[column], yerr=errors(summary, column), capsize=3)
    axes[0].axhline(IDEAL_AGGREGATE_MBPS, color="black", linestyle="--", linewidth=1, label="Ideal")
    axes[0].set_title("Aggregate Goodput")
    axes[0].set_ylabel("Mbps")
    axes[0].legend()

    column = "red_y1_mbps"
    axes[1].bar(x, summary[column], yerr=errors(summary, column), capsize=3)
    axes[1].axhline(IDEAL_PROBE_MBPS, color="black", linestyle="--", linewidth=1, label="Probe only")
    axes[1].set_title("Inefficient Path")
    axes[1].set_ylabel("Red y1 goodput (Mbps)")
    axes[1].legend()

    for ax in axes:
        ax.set_xticks(x, labels, rotation=18, ha="right")
        ax.grid(True, axis="y", alpha=0.3)
    fig.suptitle("Pareto Efficiency")
    fig.tight_layout()
    fig.savefig(out_dir / "pareto_efficiency.pdf")
    plt.close(fig)


def save_path_plot(summary: pd.DataFrame, out_dir: Path) -> None:
    labels = summary["label"].tolist()
    x = np.arange(len(summary))
    width = 0.2
    fig, ax = plt.subplots(figsize=(11.5, 5.0))

    paths = [
        ("blue_x1_mbps", "Blue x1: X"),
        ("blue_x2_mbps", "Blue x2: T"),
        ("red_y1_mbps", "Red y1: X then T"),
        ("red_y2_mbps", "Red y2: T"),
    ]
    for index, (column, path_label) in enumerate(paths):
        offset = (index - 1.5) * width
        ax.bar(
            x + offset,
            summary[column],
            width,
            yerr=errors(summary, column),
            capsize=2,
            label=path_label,
        )
    ax.set_xticks(x, labels, rotation=18, ha="right")
    ax.set_ylabel("Mbps")
    ax.set_title("Path Allocation")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(out_dir / "path_allocation.pdf")
    plt.close(fig)


def band(ax, grid: np.ndarray, series: list[pd.Series], label: str) -> None:
    matrix = np.vstack([resample(item, grid).to_numpy(dtype=float) / 1e6 for item in series])
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    ax.plot(grid, mean, label=label)
    ax.fill_between(grid, np.maximum(mean - std, 0), mean + std, alpha=0.18)


def sum_band(ax, grid: np.ndarray, groups: list[list[pd.Series]], label: str) -> None:
    matrix = np.vstack(
        [
            sum(
                (resample(item, grid).to_numpy(dtype=float) for item in group),
                start=np.zeros_like(grid),
            )
            / 1e6
            for group in groups
        ]
    )
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    ax.plot(grid, mean, label=label)
    ax.fill_between(grid, np.maximum(mean - std, 0), mean + std, alpha=0.18)


def save_protocol_plots(protocol: str, label: str, bundles: list[Bundle], out_root: Path) -> None:
    out_dir = out_root / "by_protocol" / protocol
    out_dir.mkdir(parents=True, exist_ok=True)
    grid = common_grid(bundles)

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.5))
    band(axes[0], grid, [bundle.subflows[1][0] for bundle in bundles], "Red y1")
    axes[0].axhline(IDEAL_PROBE_MBPS, color="black", linestyle="--", linewidth=1, label="Probe only")
    axes[0].set_title("Inefficient Path")
    axes[0].set_ylabel("Mbps")
    axes[0].legend()

    sum_band(axes[1], grid, [list(bundle.goodput.values()) for bundle in bundles], "Aggregate")
    axes[1].axhline(IDEAL_AGGREGATE_MBPS, color="black", linestyle="--", linewidth=1, label="Ideal")
    axes[1].set_title("Aggregate Goodput")
    axes[1].set_ylabel("Mbps")
    axes[1].legend()

    for ax in axes:
        ax.set_xlabel("Time (s)")
        ax.grid(True, alpha=0.3)
    fig.suptitle(label)
    fig.tight_layout()
    fig.savefig(out_dir / "convergence.pdf")
    plt.close(fig)


def selected_runs(args: argparse.Namespace) -> list[int]:
    if args.run is not None:
        return [args.run]
    return sorted(set(args.runs)) if args.runs else DEFAULT_RUNS


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot mptcpExperiments experiment 3.")
    parser.add_argument("--run", type=int)
    parser.add_argument("--runs", nargs="*", type=int)
    parser.add_argument("--analysis-start", type=float, default=40.0)
    args = parser.parse_args()

    sim_root = Path(__file__).resolve().parents[2]
    csv_root = sim_root / "experiments" / "experiment3" / "csvs"
    out_dir = sim_root / "plots" / "experiment3"
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

    run_summary = pd.DataFrame(
        row for bundle in bundles if (row := build_run_summary(bundle, args.analysis_start))
    )
    summary = aggregate_summary(run_summary)
    run_summary.to_csv(out_dir / "summary_runs.csv", index=False)
    summary.to_csv(out_dir / "summary.csv", index=False)
    save_pareto_plot(summary, aggregate_dir)
    save_path_plot(summary, aggregate_dir)

    grouped: dict[str, list[Bundle]] = defaultdict(list)
    for bundle in bundles:
        grouped[bundle.protocol].append(bundle)
    for protocol, label in PROTOCOLS:
        if protocol in grouped:
            save_protocol_plots(protocol, label, grouped[protocol], out_dir)

    print(f"wrote experiment 3 plots under {out_dir}")
    print(f"ideal aggregate goodput: {IDEAL_AGGREGATE_MBPS:.3f} Mbps")
    print(f"ideal Red y1 probe rate: {IDEAL_PROBE_MBPS:.3f} Mbps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
