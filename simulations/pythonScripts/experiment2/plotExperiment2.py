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
    ("cubic", "Uncoupled CUBIC"),
    ("mporb", "Uncoupled ORBCC"),
    ("olia", "OLIA"),
    ("balia", "BALIA"),
]
USERS = [
    ("A", 0, "shared paths 1-4"),
    ("B", 1, "shared 1-2, private 5-6"),
    ("C", 2, "shared 3-4, private 7-8"),
]
PATH_QUEUE_MODULES = {
    1: "sharedleopaths.router1[0].ppp[2].queue",
    2: "sharedleopaths.router1[1].ppp[2].queue",
    3: "sharedleopaths.router1[2].ppp[2].queue",
    4: "sharedleopaths.router1[3].ppp[2].queue",
    5: "sharedleopaths.router1[4].ppp[1].queue",
    6: "sharedleopaths.router1[5].ppp[1].queue",
    7: "sharedleopaths.router1[6].ppp[1].queue",
    8: "sharedleopaths.router1[7].ppp[1].queue",
}
MSS_BYTES = 1448
TOTAL_PATH_CAPACITY_MBPS = 800.0
DEFAULT_RUNS = [1, 2, 3, 4, 5]


@dataclass
class Bundle:
    run: int
    protocol: str
    label: str
    user_goodput: dict[str, pd.Series]
    subflow_throughput: dict[str, list[pd.Series]]
    subflow_cwnd: dict[str, list[pd.Series]]
    queues: dict[int, pd.Series]


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


def load_subflows(run_root: Path, host: str, user_index: int, metric: str) -> list[pd.Series]:
    prefix = f"sharedleopaths.{host}[{user_index}].tcp.conn-"
    paths = [
        path
        for path in run_root.glob(f"*/{metric}.csv")
        if path.parent.name.startswith(prefix)
    ]
    candidates = [
        series
        for path in sorted(paths, key=conn_id)
        if (series := read_series(path, metric)) is not None and not series.empty
    ]
    # Meta connections are created before their four subflows.
    return candidates[-4:]


def load_bundle(csv_root: Path, protocol: str, label: str, run: int) -> Bundle | None:
    run_root = csv_root / protocol / f"run{run}"
    user_goodput: dict[str, pd.Series] = {}
    subflow_throughput: dict[str, list[pd.Series]] = {}
    subflow_cwnd: dict[str, list[pd.Series]] = {}
    for user, index, _paths in USERS:
        app_path = run_root / f"sharedleopaths.server[{index}].app[0]" / "goodput.csv"
        goodput = read_series(app_path, "goodput")
        if goodput is None:
            print(f"warning: missing {label} run{run} user {user} goodput: {app_path}")
            return None
        user_goodput[user] = goodput
        subflow_throughput[user] = load_subflows(run_root, "server", index, "throughput")
        subflow_cwnd[user] = load_subflows(run_root, "client", index, "cwnd")

    queues: dict[int, pd.Series] = {}
    for path_index, module in PATH_QUEUE_MODULES.items():
        queue = read_series(run_root / module / "queueLength.csv", "queueLength")
        if queue is None:
            print(f"warning: missing {label} run{run} path {path_index} queue")
            return None
        queues[path_index] = queue
    return Bundle(run, protocol, label, user_goodput, subflow_throughput, subflow_cwnd, queues)


def resample(series: pd.Series | None, grid: np.ndarray) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(np.zeros_like(grid), index=grid)
    # Experiment vectors use vector(removeRepeats), so omitted samples retain
    # the previous value until the next recorded change.
    return series.reindex(series.index.union(grid)).sort_index().ffill().reindex(grid).fillna(0)


def common_grid(bundles: list[Bundle]) -> np.ndarray:
    series = []
    for bundle in bundles:
        series.extend(bundle.user_goodput.values())
        series.extend(bundle.queues.values())
        for values in bundle.subflow_throughput.values():
            series.extend(values)
        for values in bundle.subflow_cwnd.values():
            series.extend(values)
    usable = [item for item in series if item is not None and not item.empty]
    if not usable:
        return np.asarray([])
    start = max(0.0, min(float(item.index.min()) for item in usable))
    end = max(float(item.index.max()) for item in usable)
    return np.arange(start, end + 0.5, 0.5)


def final_mean(series: pd.Series, window_start: float) -> float:
    window = series[series.index >= window_start]
    if window.empty:
        window = series
    return float(window.mean()) if not window.empty else 0.0


def jain(values: np.ndarray) -> float:
    denominator = len(values) * float(np.sum(values * values))
    return float(np.sum(values) ** 2 / denominator) if denominator > 0 else 0.0


def last_positive_time(series: pd.Series) -> float | None:
    positive = series[series > 0]
    return float(positive.index.max()) if not positive.empty else None


def jain_timeseries(bundle: Bundle, grid: np.ndarray) -> pd.Series:
    matrix = np.vstack([resample(bundle.user_goodput[user], grid).to_numpy() for user, _index, _paths in USERS])
    return pd.Series([jain(matrix[:, index]) for index in range(matrix.shape[1])], index=grid)


def total_series(series: list[pd.Series], grid: np.ndarray, scale: float = 1.0) -> pd.Series:
    total = pd.Series(np.zeros_like(grid), index=grid)
    for item in series:
        total = total.add(resample(item, grid), fill_value=0)
    return total / scale


def series_stats(series_list: list[pd.Series | None], grid: np.ndarray) -> tuple[pd.Series, pd.Series]:
    sampled = [resample(series, grid).to_numpy(dtype=float) for series in series_list if series is not None]
    if not sampled:
        zeros = pd.Series(np.zeros_like(grid), index=grid)
        return zeros, zeros
    matrix = np.vstack(sampled)
    return pd.Series(matrix.mean(axis=0), index=grid), pd.Series(matrix.std(axis=0), index=grid)


def grouped_by_protocol(bundles: list[Bundle]) -> list[tuple[str, str, list[Bundle]]]:
    grouped: dict[str, list[Bundle]] = defaultdict(list)
    for bundle in bundles:
        grouped[bundle.protocol].append(bundle)
    return [(protocol, label, grouped[protocol]) for protocol, label in PROTOCOLS if protocol in grouped]


def build_run_summary(bundle: Bundle, final_window: float, analysis_start: float) -> dict[str, float | int | str | None]:
    grid = common_grid([bundle])
    if len(grid) == 0:
        return {}
    final_window_start = max(float(grid.max()) - final_window, float(grid.min()))
    analysis_end = float(grid.max())
    row: dict[str, float | int | str | None] = {
        "run": bundle.run,
        "protocol": bundle.protocol,
        "label": bundle.label,
        "analysis_start_time_s": analysis_start,
        "analysis_end_time_s": analysis_end,
        "final_window_start_time_s": final_window_start,
    }
    final_goodputs = []
    run_goodputs = []
    for user, _index, _paths in USERS:
        app_goodput = resample(bundle.user_goodput[user], grid)
        final_goodput = final_mean(app_goodput / 1e6, final_window_start)
        run_goodput = final_mean(app_goodput / 1e6, analysis_start)
        last_delivery_time = last_positive_time(app_goodput)
        row[f"user_{user}_goodput_mbps"] = final_goodput
        row[f"user_{user}_run_average_goodput_mbps"] = run_goodput
        row[f"user_{user}_last_positive_goodput_time_s"] = last_delivery_time
        row[f"user_{user}_delivery_stall_duration_s"] = (
            max(analysis_end - last_delivery_time, 0.0) if last_delivery_time is not None else None
        )
        row[f"user_{user}_total_cwnd_packets"] = final_mean(
            total_series(bundle.subflow_cwnd[user], grid, MSS_BYTES), final_window_start
        )
        final_goodputs.append(final_goodput)
        run_goodputs.append(run_goodput)
    aggregate = float(np.sum(final_goodputs))
    run_aggregate = float(np.sum(run_goodputs))
    row["aggregate_goodput_mbps"] = aggregate
    row["run_average_aggregate_goodput_mbps"] = run_aggregate
    row["jain_fairness"] = jain(np.asarray(final_goodputs))
    row["run_average_jain_fairness"] = jain(np.asarray(run_goodputs))
    row["a_vs_bc_mean_ratio"] = (
        final_goodputs[0] / float(np.mean(final_goodputs[1:])) if np.mean(final_goodputs[1:]) > 0 else 0.0
    )
    row["run_average_a_vs_bc_mean_ratio"] = (
        run_goodputs[0] / float(np.mean(run_goodputs[1:])) if np.mean(run_goodputs[1:]) > 0 else 0.0
    )
    row["aggregate_path_utilization"] = aggregate / TOTAL_PATH_CAPACITY_MBPS
    row["run_average_aggregate_path_utilization"] = run_aggregate / TOTAL_PATH_CAPACITY_MBPS
    for path in PATH_QUEUE_MODULES:
        row[f"path_{path}_queue_packets"] = final_mean(resample(bundle.queues[path], grid), final_window_start)
    row["shared_queue_packets"] = float(np.mean([row[f"path_{path}_queue_packets"] for path in range(1, 5)]))
    row["private_queue_packets"] = float(np.mean([row[f"path_{path}_queue_packets"] for path in range(5, 9)]))
    return row


def aggregate_summary(run_summary: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["protocol", "label"]
    numeric_cols = [column for column in run_summary.select_dtypes(include=[np.number]).columns if column != "run"]
    rows = []
    for keys, group in run_summary.groupby(key_cols, sort=False):
        row = dict(zip(key_cols, keys))
        row["run_count"] = int(group["run"].nunique())
        for column in numeric_cols:
            values = group[column].dropna().astype(float)
            row[column] = float(values.mean()) if not values.empty else np.nan
            row[f"{column}_std"] = float(values.std(ddof=0)) if not values.empty else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def save_user_goodput_timeseries(protocol_groups: list[tuple[str, str, list[Bundle]]], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(len(protocol_groups), 1, figsize=(10, 9), sharex=True, sharey=True)
    axes = np.atleast_1d(axes)
    for ax, (_protocol, label, group) in zip(axes, protocol_groups):
        for user, _index, paths in USERS:
            mean, std = series_stats([bundle.user_goodput[user] for bundle in group], grid)
            mean_mbps = mean / 1e6
            std_mbps = std / 1e6
            ax.plot(grid, mean_mbps, label=f"{user}: {paths}")
            ax.fill_between(grid, mean_mbps - std_mbps, mean_mbps + std_mbps, alpha=0.16)
        ax.set_title(f"{label} (n={len(group)})")
        ax.set_ylabel("Mbps")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle("Per-Connection Goodput")
    fig.tight_layout()
    fig.savefig(out_dir / "per_user_goodput_timeseries.pdf")
    plt.close(fig)


def save_subflow_timeseries(protocol_groups: list[tuple[str, str, list[Bundle]]], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(len(protocol_groups), len(USERS), figsize=(14, 10), sharex=True, sharey=True)
    axes = np.asarray(axes).reshape(len(protocol_groups), len(USERS))
    for row, (_protocol, label, group) in enumerate(protocol_groups):
        for col, (user, _index, paths) in enumerate(USERS):
            ax = axes[row, col]
            max_subflows = max((len(bundle.subflow_throughput[user]) for bundle in group), default=0)
            for sf in range(max_subflows):
                mean, std = series_stats(
                    [
                        bundle.subflow_throughput[user][sf]
                        if sf < len(bundle.subflow_throughput[user])
                        else None
                        for bundle in group
                    ],
                    grid,
                )
                mean_mbps = mean / 1e6
                std_mbps = std / 1e6
                ax.plot(grid, mean_mbps, label=f"sf {sf + 1}")
                ax.fill_between(grid, mean_mbps - std_mbps, mean_mbps + std_mbps, alpha=0.12)
            ax.set_title(f"{label}: {user}\n{paths}")
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=7)
    for ax in axes[-1, :]:
        ax.set_xlabel("Time (s)")
    for ax in axes[:, 0]:
        ax.set_ylabel("Throughput (Mbps)")
    fig.suptitle("Per-Subflow Throughput")
    fig.tight_layout()
    fig.savefig(out_dir / "per_subflow_goodput_timeseries.pdf")
    plt.close(fig)


def save_cwnd_timeseries(protocol_groups: list[tuple[str, str, list[Bundle]]], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(len(protocol_groups), len(USERS), figsize=(14, 10), sharex=True, sharey=True)
    axes = np.asarray(axes).reshape(len(protocol_groups), len(USERS))
    for row, (_protocol, label, group) in enumerate(protocol_groups):
        for col, (user, _index, _paths) in enumerate(USERS):
            ax = axes[row, col]
            max_subflows = max((len(bundle.subflow_cwnd[user]) for bundle in group), default=0)
            for sf in range(max_subflows):
                mean, std = series_stats(
                    [bundle.subflow_cwnd[user][sf] if sf < len(bundle.subflow_cwnd[user]) else None for bundle in group],
                    grid,
                )
                mean_packets = mean / MSS_BYTES
                std_packets = std / MSS_BYTES
                ax.plot(grid, mean_packets, label=f"sf {sf + 1}")
                ax.fill_between(grid, mean_packets - std_packets, mean_packets + std_packets, alpha=0.12)
            ax.set_title(f"{label}: connection {user}")
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=7)
    for ax in axes[-1, :]:
        ax.set_xlabel("Time (s)")
    for ax in axes[:, 0]:
        ax.set_ylabel("cwnd (MSS packets)")
    fig.suptitle("Per-Subflow Congestion Windows")
    fig.tight_layout()
    fig.savefig(out_dir / "per_subflow_cwnd_timeseries.pdf")
    plt.close(fig)


def save_queue_timeseries(protocol_groups: list[tuple[str, str, list[Bundle]]], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(len(protocol_groups), 1, figsize=(11, 9), sharex=True, sharey=True)
    axes = np.atleast_1d(axes)
    for ax, (_protocol, label, group) in zip(axes, protocol_groups):
        for path in PATH_QUEUE_MODULES:
            kind = "shared" if path <= 4 else "private"
            mean, std = series_stats([bundle.queues[path] for bundle in group], grid)
            ax.plot(grid, mean, label=f"path {path} ({kind})")
            ax.fill_between(grid, mean - std, mean + std, alpha=0.08)
        ax.set_title(f"{label} (n={len(group)})")
        ax.set_ylabel("Packets")
        ax.grid(True, alpha=0.3)
        ax.legend(ncol=4, fontsize=7)
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle("Per-Path Forward Queue Occupancy")
    fig.tight_layout()
    fig.savefig(out_dir / "per_path_queue_occupancy_timeseries.pdf")
    plt.close(fig)


def save_jain_timeseries(protocol_groups: list[tuple[str, str, list[Bundle]]], grid: np.ndarray, out_dir: Path) -> None:
    plt.figure(figsize=(9, 4.5))
    for _protocol, label, group in protocol_groups:
        mean, std = series_stats([jain_timeseries(bundle, grid) for bundle in group], grid)
        plt.plot(grid, mean, label=f"{label} (n={len(group)})")
        plt.fill_between(grid, mean - std, mean + std, alpha=0.16)
    plt.xlabel("Time (s)")
    plt.ylabel("Jain fairness across A, B, C")
    plt.ylim(0.75, 1.01)
    plt.title("Connection Fairness")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_dir / "jain_fairness_timeseries.pdf")
    plt.close()


def save_aggregate_plots(summary: pd.DataFrame, out_dir: Path) -> None:
    labels = summary["label"].tolist()
    x = np.arange(len(summary))
    width = 0.23

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    for offset, user in zip((-width, 0, width), ("A", "B", "C")):
        axes[0].bar(
            x + offset,
            summary[f"user_{user}_goodput_mbps"],
            width,
            yerr=summary.get(f"user_{user}_goodput_mbps_std"),
            capsize=3,
            label=f"connection {user}",
        )
    axes[0].set_title("Per-Connection Goodput")
    axes[0].set_ylabel("Mbps")
    axes[0].legend(fontsize=8)
    axes[1].bar(x, summary["jain_fairness"], yerr=summary.get("jain_fairness_std"), capsize=3)
    axes[1].set_title("Jain Fairness")
    axes[1].set_ylim(0.75, 1.01)
    axes[2].bar(x, summary["a_vs_bc_mean_ratio"], yerr=summary.get("a_vs_bc_mean_ratio_std"), capsize=3)
    axes[2].axhline(1.0, color="black", linestyle="--", linewidth=1)
    axes[2].set_title("A / Mean(B,C)")
    for ax in axes:
        ax.set_xticks(x, labels, rotation=20, ha="right")
        ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "fairness_and_goodput_summary.pdf")
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    for offset, user in zip((-width, 0, width), ("A", "B", "C")):
        axes[0].bar(
            x + offset,
            summary[f"user_{user}_run_average_goodput_mbps"],
            width,
            yerr=summary.get(f"user_{user}_run_average_goodput_mbps_std"),
            capsize=3,
            label=f"connection {user}",
        )
    axes[0].set_title("Post-Join Per-Connection Goodput")
    axes[0].set_ylabel("Mbps")
    axes[0].legend(fontsize=8)
    axes[1].bar(
        x,
        summary["run_average_jain_fairness"],
        yerr=summary.get("run_average_jain_fairness_std"),
        capsize=3,
    )
    axes[1].set_title("Post-Join Jain Fairness")
    axes[1].set_ylim(0.75, 1.01)
    axes[2].bar(
        x,
        summary["run_average_a_vs_bc_mean_ratio"],
        yerr=summary.get("run_average_a_vs_bc_mean_ratio_std"),
        capsize=3,
    )
    axes[2].axhline(1.0, color="black", linestyle="--", linewidth=1)
    axes[2].set_title("Post-Join A / Mean(B,C)")
    for ax in axes:
        ax.set_xticks(x, labels, rotation=20, ha="right")
        ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "whole_run_fairness_and_goodput_summary.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4.5))
    for offset, user in zip((-width, 0, width), ("A", "B", "C")):
        ax.bar(
            x + offset,
            summary[f"user_{user}_last_positive_goodput_time_s"],
            width,
            yerr=summary.get(f"user_{user}_last_positive_goodput_time_s_std"),
            capsize=3,
            label=f"connection {user}",
        )
    ax.set_title("Application Delivery Cutoff")
    ax.set_ylabel("Last positive app-goodput sample (s)")
    ax.set_xticks(x, labels, rotation=20, ha="right")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "app_delivery_cutoff_summary.pdf")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    axes[0].bar(
        x - width / 2,
        summary["shared_queue_packets"],
        width,
        yerr=summary.get("shared_queue_packets_std"),
        capsize=3,
        label="shared paths 1-4",
    )
    axes[0].bar(
        x + width / 2,
        summary["private_queue_packets"],
        width,
        yerr=summary.get("private_queue_packets_std"),
        capsize=3,
        label="private paths 5-8",
    )
    axes[0].set_title("Mean Queue Occupancy")
    axes[0].set_ylabel("Packets")
    axes[0].legend(fontsize=8)
    axes[1].bar(
        x - width / 2,
        summary["aggregate_goodput_mbps"],
        width,
        yerr=summary.get("aggregate_goodput_mbps_std"),
        capsize=3,
        label="final window",
    )
    axes[1].bar(
        x + width / 2,
        summary["run_average_aggregate_goodput_mbps"],
        width,
        yerr=summary.get("run_average_aggregate_goodput_mbps_std"),
        capsize=3,
        label="post-join",
    )
    axes[1].set_title("Aggregate Goodput")
    axes[1].set_ylabel("Mbps")
    axes[1].legend(fontsize=8)
    for ax in axes:
        ax.set_xticks(x, labels, rotation=20, ha="right")
        ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "utilization_and_queue_summary.pdf")
    plt.close(fig)

    queue_columns = [f"path_{path}_queue_packets" for path in PATH_QUEUE_MODULES]
    matrix = summary[queue_columns].to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    image = ax.imshow(matrix, aspect="auto", cmap="viridis")
    ax.set_title("Final-Window Queue Occupancy by Path")
    ax.set_xlabel("Path (1-4 shared, 5-8 private)")
    ax.set_yticks(np.arange(len(summary)), labels)
    ax.set_xticks(np.arange(8), [str(path) for path in PATH_QUEUE_MODULES])
    for row in range(matrix.shape[0]):
        for col in range(matrix.shape[1]):
            ax.text(col, row, f"{matrix[row, col]:.0f}", ha="center", va="center", color="white", fontsize=8)
    fig.colorbar(image, ax=ax, label="Packets")
    fig.tight_layout()
    fig.savefig(out_dir / "queue_occupancy_heatmap.pdf")
    plt.close(fig)


def save_protocol_plots(protocol: str, label: str, group: list[Bundle], out_root: Path) -> None:
    out_dir = out_root / "by_protocol" / protocol
    out_dir.mkdir(parents=True, exist_ok=True)
    grid = common_grid(group)
    if len(grid) == 0:
        return
    protocol_groups = [(protocol, label, group)]
    save_user_goodput_timeseries(protocol_groups, grid, out_dir)
    save_subflow_timeseries(protocol_groups, grid, out_dir)
    save_cwnd_timeseries(protocol_groups, grid, out_dir)
    save_queue_timeseries(protocol_groups, grid, out_dir)
    save_jain_timeseries(protocol_groups, grid, out_dir)


def selected_runs(args: argparse.Namespace) -> list[int]:
    if args.run is not None:
        return [args.run]
    if args.runs:
        return sorted(set(args.runs))
    return DEFAULT_RUNS


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot mptcpExperiments experiment 2.")
    parser.add_argument("--run", type=int, help="Plot one run only.")
    parser.add_argument("--runs", nargs="*", type=int, help="Runs to aggregate; default is 1 2 3 4 5.")
    parser.add_argument("--final-window", type=float, default=60.0)
    parser.add_argument(
        "--analysis-start",
        type=float,
        default=10.0,
        help="Start time for post-join run averages. Defaults to 10s, after the 0-5s random join window.",
    )
    args = parser.parse_args()
    runs = selected_runs(args)

    sim_root = Path(__file__).resolve().parents[2]
    csv_root = sim_root / "experiments" / "experiment2" / "csvs"
    out_dir = sim_root / "plots" / "experiment2"
    shutil.rmtree(out_dir, ignore_errors=True)
    aggregate_dir = out_dir / "aggregate"
    aggregate_dir.mkdir(parents=True, exist_ok=True)

    bundles = [
        bundle
        for run in runs
        for protocol, label in PROTOCOLS
        if (bundle := load_bundle(csv_root, protocol, label, run)) is not None
    ]
    if not bundles:
        print(f"no extracted CSV data found under {csv_root}")
        return 1
    grid = common_grid(bundles)
    if len(grid) == 0:
        print("no usable timeseries data found")
        return 1

    run_summary = pd.DataFrame(
        row
        for bundle in bundles
        if (row := build_run_summary(bundle, args.final_window, args.analysis_start))
    )
    summary = aggregate_summary(run_summary)
    run_summary.to_csv(out_dir / "summary_runs_final_window.csv", index=False)
    run_summary.to_csv(aggregate_dir / "summary_runs_final_window.csv", index=False)
    summary.to_csv(out_dir / "summary_final_window.csv", index=False)
    summary.to_csv(aggregate_dir / "summary_final_window.csv", index=False)

    protocol_groups = grouped_by_protocol(bundles)
    save_user_goodput_timeseries(protocol_groups, grid, aggregate_dir)
    save_subflow_timeseries(protocol_groups, grid, aggregate_dir)
    save_cwnd_timeseries(protocol_groups, grid, aggregate_dir)
    save_queue_timeseries(protocol_groups, grid, aggregate_dir)
    save_jain_timeseries(protocol_groups, grid, aggregate_dir)
    save_aggregate_plots(summary, aggregate_dir)
    for protocol, label, group in protocol_groups:
        save_protocol_plots(protocol, label, group, out_dir)

    print(f"wrote aggregate plots under {aggregate_dir}")
    print(f"wrote per-protocol plots under {out_dir / 'by_protocol'}")
    print(f"aggregated runs: {', '.join(str(run) for run in runs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
