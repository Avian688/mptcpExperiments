#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CONFIGS = [
    ("cubic", "Uncoupled CUBIC"),
    ("mporb", "Uncoupled ORBCC"),
]

USERS = [
    ("A", 0, "paths 1-4"),
    ("B", 1, "paths 1,2,5,6"),
    ("C", 2, "paths 3,4,7,8"),
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


@dataclass
class SeriesBundle:
    protocol: str
    label: str
    user_goodput: dict[str, pd.Series]
    subflows: dict[str, list[pd.Series]]
    queues: dict[int, pd.Series]
    hol_blocked: dict[str, pd.Series | None]
    dsn_gap: dict[str, pd.Series | None]


def read_series(path: Path, column: str) -> pd.Series | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if "time" not in df.columns or column not in df.columns:
        return None
    series = pd.Series(df[column].to_numpy(dtype=float), index=df["time"].to_numpy(dtype=float))
    return series[~series.index.duplicated(keep="last")].sort_index()


def resample_to_grid(series: pd.Series | None, grid: np.ndarray) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(np.zeros_like(grid), index=grid)
    return series.reindex(series.index.union(grid)).interpolate(method="index").reindex(grid).fillna(0)


def sample_hold_to_grid(series: pd.Series | None, grid: np.ndarray) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(np.zeros_like(grid), index=grid)
    return series.reindex(series.index.union(grid)).sort_index().ffill().reindex(grid).fillna(0)


def bytes_to_packets(series: pd.Series) -> pd.Series:
    return series / MSS_BYTES


def conn_id(path: Path) -> int:
    match = re.search(r"\.conn-(\d+)$", path.parent.name)
    return int(match.group(1)) if match else 10**9


def load_subflows(run_root: Path, server_index: int) -> list[pd.Series]:
    prefix = f"sharedleopaths.server[{server_index}].tcp.conn-"
    paths = [
        path
        for path in run_root.glob("*/throughput.csv")
        if path.parent.name.startswith(prefix)
    ]
    series = [
        item
        for path in sorted(paths, key=conn_id)
        if (item := read_series(path, "throughput")) is not None and float(item.mean()) > 1000
    ]
    return series[:4]


def load_connection_series(run_root: Path, server_index: int, metric: str) -> pd.Series | None:
    prefix = f"sharedleopaths.server[{server_index}].tcp.conn-"
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
    return max(candidates, key=len) if candidates else None


def load_bundle(csv_root: Path, protocol: str, label: str, run: int) -> SeriesBundle | None:
    run_root = csv_root / protocol / f"run{run}"
    user_goodput: dict[str, pd.Series] = {}
    subflows: dict[str, list[pd.Series]] = {}
    queues: dict[int, pd.Series] = {}
    hol_blocked: dict[str, pd.Series | None] = {}
    dsn_gap: dict[str, pd.Series | None] = {}

    for user_label, server_index, _paths in USERS:
        app_path = run_root / f"sharedleopaths.server[{server_index}].app[0]" / "goodput.csv"
        app_goodput = read_series(app_path, "goodput")
        if app_goodput is None:
            print(f"warning: missing app goodput for {label} user {user_label}: {app_path}")
            return None
        user_goodput[user_label] = app_goodput
        subflows[user_label] = load_subflows(run_root, server_index)
        hol_blocked[user_label] = load_connection_series(run_root, server_index, "holBlockedBytes")
        dsn_gap[user_label] = load_connection_series(run_root, server_index, "metaDsnGapBytes")

    for path_index, module in PATH_QUEUE_MODULES.items():
        queue = read_series(run_root / module / "queueLength.csv", "queueLength")
        if queue is not None:
            queues[path_index] = queue
        else:
            print(f"warning: missing path {path_index} queueLength for {label}")

    return SeriesBundle(protocol, label, user_goodput, subflows, queues, hol_blocked, dsn_gap)


def common_grid(bundles: list[SeriesBundle]) -> np.ndarray:
    starts = []
    ends = []
    for bundle in bundles:
        all_series = (
            list(bundle.user_goodput.values())
            + list(bundle.queues.values())
            + list(bundle.hol_blocked.values())
            + list(bundle.dsn_gap.values())
        )
        for subflow_list in bundle.subflows.values():
            all_series.extend(subflow_list)
        starts.extend(float(series.index.min()) for series in all_series if series is not None and not series.empty)
        ends.extend(float(series.index.max()) for series in all_series if series is not None and not series.empty)
    if not starts or not ends:
        return np.asarray([])
    return np.arange(max(min(starts), 0.0), max(ends) + 0.5, 0.5)


def jain(values: np.ndarray) -> float:
    denominator = len(values) * float(np.sum(values * values))
    if denominator <= 0:
        return 0.0
    return float(np.sum(values) ** 2 / denominator)


def jain_series(bundle: SeriesBundle, grid: np.ndarray) -> pd.Series:
    user_matrix = np.vstack([
        resample_to_grid(bundle.user_goodput[user_label], grid).to_numpy()
        for user_label, _server_index, _paths in USERS
    ])
    values = np.asarray([jain(user_matrix[:, index]) for index in range(user_matrix.shape[1])])
    return pd.Series(values, index=grid)


def final_window_mean(series: pd.Series, start_time: float) -> float:
    window = series[series.index >= start_time]
    if window.empty:
        window = series
    return float(window.mean()) if not window.empty else 0.0


def save_user_goodput_plot(bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(len(bundles), 1, figsize=(10, 6), sharex=True, sharey=True)
    axes = np.atleast_1d(axes)
    for ax, bundle in zip(axes, bundles):
        for user_label, _server_index, paths in USERS:
            series = resample_to_grid(bundle.user_goodput[user_label], grid) / 1e6
            ax.plot(grid, series, label=f"user {user_label} ({paths})")
        ax.set_title(bundle.label)
        ax.set_ylabel("Goodput (Mbps)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle("Per-User Application Goodput")
    fig.tight_layout()
    fig.savefig(out_dir / "per_user_goodput_timeseries.pdf")
    plt.close(fig)


def save_subflow_plot(bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(len(bundles), len(USERS), figsize=(13, 6), sharex=True, sharey=True)
    axes = np.asarray(axes)
    if axes.ndim == 1:
        axes = axes.reshape(1, -1)

    for row, bundle in enumerate(bundles):
        for col, (user_label, _server_index, paths) in enumerate(USERS):
            ax = axes[row, col]
            for index, series in enumerate(bundle.subflows[user_label], start=1):
                ax.plot(grid, resample_to_grid(series, grid) / 1e6, label=f"sf {index}")
            ax.set_title(f"{bundle.label}: user {user_label}\n{paths}")
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=8)
    for ax in axes[-1, :]:
        ax.set_xlabel("Time (s)")
    for ax in axes[:, 0]:
        ax.set_ylabel("Subflow throughput (Mbps)")
    fig.suptitle("Per-Subflow Goodput Proxy")
    fig.tight_layout()
    fig.savefig(out_dir / "per_subflow_goodput_timeseries.pdf")
    plt.close(fig)


def save_queue_plot(bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(len(bundles), 1, figsize=(11, 6), sharex=True, sharey=True)
    axes = np.atleast_1d(axes)
    for ax, bundle in zip(axes, bundles):
        for path_index in sorted(PATH_QUEUE_MODULES):
            if path_index not in bundle.queues:
                continue
            ax.plot(grid, resample_to_grid(bundle.queues[path_index], grid), label=f"path {path_index}")
        ax.set_title(bundle.label)
        ax.set_ylabel("Queue length (packets)")
        ax.grid(True, alpha=0.3)
        ax.legend(ncol=4, fontsize=8)
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle("Per-Path Forward Bottleneck Queue Occupancy")
    fig.tight_layout()
    fig.savefig(out_dir / "per_path_queue_occupancy_timeseries.pdf")
    plt.close(fig)


def save_jain_plot(bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    plt.figure(figsize=(10, 4))
    for bundle in bundles:
        plt.plot(grid, jain_series(bundle, grid), label=bundle.label)
    plt.xlabel("Time (s)")
    plt.ylabel("Jain fairness across users")
    plt.ylim(0, 1.05)
    plt.title("Per-User Jain Fairness")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_dir / "jain_fairness_timeseries.pdf")
    plt.close()


def save_hol_blocked_plot(bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    (out_dir / "hol_blocked_bytes_timeseries.pdf").unlink(missing_ok=True)
    fig, axes = plt.subplots(len(bundles), 1, figsize=(10, 6), sharex=True, sharey=True)
    axes = np.atleast_1d(axes)
    for ax, bundle in zip(axes, bundles):
        for user_label, _server_index, paths in USERS:
            series = bytes_to_packets(sample_hold_to_grid(bundle.hol_blocked.get(user_label), grid))
            ax.plot(grid, series, label=f"user {user_label} ({paths})")
        ax.set_title(bundle.label)
        ax.set_ylabel("HoL blocked (MSS packets)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle("Receiver HoL-Blocked Data")
    fig.tight_layout()
    fig.savefig(out_dir / "hol_blocked_packets_timeseries.pdf")
    plt.close(fig)


def save_dsn_gap_plot(bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(len(bundles), 1, figsize=(10, 6), sharex=True, sharey=True)
    axes = np.atleast_1d(axes)
    for ax, bundle in zip(axes, bundles):
        for user_label, _server_index, paths in USERS:
            series = bytes_to_packets(sample_hold_to_grid(bundle.dsn_gap.get(user_label), grid))
            ax.plot(grid, series, label=f"user {user_label} ({paths})")
        ax.set_title(bundle.label)
        ax.set_ylabel("DSN gap (MSS packets)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle("Receiver DSN Gap")
    fig.tight_layout()
    fig.savefig(out_dir / "dsn_gap_timeseries.pdf")
    plt.close(fig)


def save_summary(bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path, final_window: float) -> pd.DataFrame:
    rows = []
    window_start = max(float(grid.max()) - final_window, float(grid.min())) if len(grid) else 0.0
    for bundle in bundles:
        row = {"protocol": bundle.protocol, "label": bundle.label}
        user_means = []
        for user_label, _server_index, _paths in USERS:
            mean_mbps = final_window_mean(resample_to_grid(bundle.user_goodput[user_label], grid) / 1e6, window_start)
            row[f"user_{user_label}_goodput_mbps"] = mean_mbps
            row[f"user_{user_label}_hol_blocked_packets"] = final_window_mean(
                bytes_to_packets(sample_hold_to_grid(bundle.hol_blocked.get(user_label), grid)),
                window_start,
            )
            row[f"user_{user_label}_dsn_gap_packets"] = final_window_mean(
                bytes_to_packets(sample_hold_to_grid(bundle.dsn_gap.get(user_label), grid)),
                window_start,
            )
            user_means.append(mean_mbps)
        row["jain_fairness"] = jain(np.asarray(user_means))
        row["a_vs_mean_ratio"] = user_means[0] / float(np.mean(user_means)) if np.mean(user_means) > 0 else 0.0
        row["a_vs_bc_mean_ratio"] = user_means[0] / float(np.mean(user_means[1:])) if np.mean(user_means[1:]) > 0 else 0.0
        for path_index in sorted(PATH_QUEUE_MODULES):
            row[f"path_{path_index}_queue_pkts"] = final_window_mean(
                resample_to_grid(bundle.queues.get(path_index), grid),
                window_start,
            )
        rows.append(row)

    summary = pd.DataFrame(rows)
    summary.to_csv(out_dir / "summary_final_window.csv", index=False)

    labels = summary["label"].tolist()
    x = np.arange(len(summary))
    width = 0.22
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    for offset, user_label in zip((-width, 0, width), ("A", "B", "C")):
        axes[0].bar(x + offset, summary[f"user_{user_label}_goodput_mbps"], width, label=f"user {user_label}")
    axes[0].set_title("Final-Window Per-User Goodput")
    axes[0].set_ylabel("Mbps")
    axes[0].set_xticks(x, labels, rotation=20, ha="right")
    axes[0].grid(True, axis="y", alpha=0.3)
    axes[0].legend(fontsize=8)

    axes[1].bar(x, summary["jain_fairness"])
    axes[1].set_title("Final-Window Jain Fairness")
    axes[1].set_ylim(0, 1.05)
    axes[1].set_xticks(x, labels, rotation=20, ha="right")
    axes[1].grid(True, axis="y", alpha=0.3)

    axes[2].bar(x, summary["a_vs_bc_mean_ratio"])
    axes[2].set_title("User A / Mean(B,C)")
    axes[2].set_ylim(0, 1.1)
    axes[2].set_xticks(x, labels, rotation=20, ha="right")
    axes[2].grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / "summary_final_window.pdf")
    plt.close(fig)
    return summary


def save_aggregate_summary_plots(summary: pd.DataFrame, out_dir: Path) -> None:
    aggregate_dir = out_dir / "aggregate"
    aggregate_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(aggregate_dir / "summary_final_window.csv", index=False)

    labels = summary["label"].tolist()
    x = np.arange(len(summary))
    width = 0.22

    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for offset, user_label in zip((-width, 0, width), ("A", "B", "C")):
        axes[0].bar(x + offset, summary[f"user_{user_label}_goodput_mbps"], width, label=f"user {user_label}")
    axes[0].set_title("Per-User Goodput")
    axes[0].set_ylabel("Mbps")
    axes[0].set_xticks(x, labels, rotation=20, ha="right")
    axes[0].grid(True, axis="y", alpha=0.3)
    axes[0].legend(fontsize=8)

    axes[1].bar(x, summary["jain_fairness"])
    axes[1].set_title("Jain Fairness")
    axes[1].set_ylim(0, 1.05)
    axes[1].set_xticks(x, labels, rotation=20, ha="right")
    axes[1].grid(True, axis="y", alpha=0.3)

    axes[2].bar(x, summary["a_vs_bc_mean_ratio"])
    axes[2].set_title("User A / Mean(B,C)")
    axes[2].set_ylim(0, 1.1)
    axes[2].set_xticks(x, labels, rotation=20, ha="right")
    axes[2].grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(aggregate_dir / "fairness_and_goodput_summary.pdf")
    plt.close(fig)

    hol_columns = [f"user_{user}_hol_blocked_packets" for user in ("A", "B", "C")]
    dsn_columns = [f"user_{user}_dsn_gap_packets" for user in ("A", "B", "C")]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for offset, user_label, column in zip((-width, 0, width), ("A", "B", "C"), hol_columns):
        axes[0].bar(x + offset, summary[column], width, label=f"user {user_label}")
    axes[0].set_title("Final-Window HoL-Blocked Data")
    axes[0].set_ylabel("MSS packets")
    axes[0].set_xticks(x, labels, rotation=20, ha="right")
    axes[0].grid(True, axis="y", alpha=0.3)
    axes[0].legend(fontsize=8)

    for offset, user_label, column in zip((-width, 0, width), ("A", "B", "C"), dsn_columns):
        axes[1].bar(x + offset, summary[column], width, label=f"user {user_label}")
    axes[1].set_title("Final-Window DSN Gap")
    axes[1].set_ylabel("MSS packets")
    axes[1].set_xticks(x, labels, rotation=20, ha="right")
    axes[1].grid(True, axis="y", alpha=0.3)
    axes[1].legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(aggregate_dir / "hol_summary.pdf")
    plt.close(fig)

    queue_columns = [f"path_{path_index}_queue_pkts" for path_index in sorted(PATH_QUEUE_MODULES)]
    if all(column in summary.columns for column in queue_columns):
        matrix = summary[queue_columns].to_numpy(dtype=float)
        fig, ax = plt.subplots(figsize=(10, max(2.8, 0.7 * len(summary))))
        image = ax.imshow(matrix, aspect="auto", cmap="viridis")
        ax.set_title("Final-Window Forward Queue Occupancy")
        ax.set_xlabel("Path")
        ax.set_ylabel("Protocol")
        ax.set_xticks(np.arange(len(queue_columns)), [str(index) for index in sorted(PATH_QUEUE_MODULES)])
        ax.set_yticks(np.arange(len(summary)), labels)
        for row in range(matrix.shape[0]):
            for col in range(matrix.shape[1]):
                ax.text(col, row, f"{matrix[row, col]:.0f}", ha="center", va="center", color="white", fontsize=8)
        cbar = fig.colorbar(image, ax=ax)
        cbar.set_label("Queue length (packets)")
        fig.tight_layout()
        fig.savefig(aggregate_dir / "queue_occupancy_heatmap.pdf")
        plt.close(fig)


def save_protocol_plots(bundle: SeriesBundle, out_root: Path, final_window: float) -> None:
    out_dir = out_root / "by_protocol" / bundle.protocol
    out_dir.mkdir(parents=True, exist_ok=True)
    grid = common_grid([bundle])
    if len(grid) == 0:
        return
    save_user_goodput_plot([bundle], grid, out_dir)
    save_subflow_plot([bundle], grid, out_dir)
    save_queue_plot([bundle], grid, out_dir)
    save_jain_plot([bundle], grid, out_dir)
    save_hol_blocked_plot([bundle], grid, out_dir)
    save_dsn_gap_plot([bundle], grid, out_dir)
    save_summary([bundle], grid, out_dir, final_window)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot mptcpExperiments experiment 2.")
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--final-window", type=float, default=60.0)
    args = parser.parse_args()

    sim_root = Path(__file__).resolve().parents[2]
    experiment_root = sim_root / "experiments" / "experiment2"
    csv_root = experiment_root / "csvs"
    out_dir = sim_root / "plots" / "experiment2"
    out_dir.mkdir(parents=True, exist_ok=True)

    bundles = [
        bundle
        for protocol, label in CONFIGS
        if (bundle := load_bundle(csv_root, protocol, label, args.run)) is not None
    ]
    if not bundles:
        print(f"no extracted CSV data found under {csv_root}")
        return 1

    grid = common_grid(bundles)
    if len(grid) == 0:
        print("no usable timeseries data found")
        return 1

    summary = save_summary(bundles, grid, out_dir, args.final_window)
    save_aggregate_summary_plots(summary, out_dir)
    for bundle in bundles:
        save_protocol_plots(bundle, out_dir, args.final_window)
    print(f"wrote aggregate plots under {out_dir / 'aggregate'}")
    print(f"wrote per-protocol plots under {out_dir / 'by_protocol'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
