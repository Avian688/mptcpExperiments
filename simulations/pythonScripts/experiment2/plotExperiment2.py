#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import shutil
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


@dataclass
class Bundle:
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
            print(f"warning: missing {label} user {user} goodput: {app_path}")
            return None
        user_goodput[user] = goodput
        subflow_throughput[user] = load_subflows(run_root, "server", index, "throughput")
        subflow_cwnd[user] = load_subflows(run_root, "client", index, "cwnd")

    queues: dict[int, pd.Series] = {}
    for path_index, module in PATH_QUEUE_MODULES.items():
        queue = read_series(run_root / module / "queueLength.csv", "queueLength")
        if queue is None:
            print(f"warning: missing {label} path {path_index} queue")
            return None
        queues[path_index] = queue
    return Bundle(protocol, label, user_goodput, subflow_throughput, subflow_cwnd, queues)


def resample(series: pd.Series | None, grid: np.ndarray, sample_hold: bool = False) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(np.zeros_like(grid), index=grid)
    expanded = series.reindex(series.index.union(grid)).sort_index()
    expanded = expanded.ffill() if sample_hold else expanded.interpolate(method="index")
    return expanded.reindex(grid).fillna(0)


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


def jain_timeseries(bundle: Bundle, grid: np.ndarray) -> pd.Series:
    matrix = np.vstack([resample(bundle.user_goodput[user], grid).to_numpy() for user, _index, _paths in USERS])
    return pd.Series([jain(matrix[:, index]) for index in range(matrix.shape[1])], index=grid)


def total_series(series: list[pd.Series], grid: np.ndarray, scale: float = 1.0) -> pd.Series:
    total = pd.Series(np.zeros_like(grid), index=grid)
    for item in series:
        total = total.add(resample(item, grid), fill_value=0)
    return total / scale


def build_summary(bundles: list[Bundle], final_window: float) -> pd.DataFrame:
    rows = []
    for bundle in bundles:
        grid = common_grid([bundle])
        if len(grid) == 0:
            continue
        window_start = max(float(grid.max()) - final_window, float(grid.min()))
        row = {"protocol": bundle.protocol, "label": bundle.label}
        goodputs = []
        for user, _index, _paths in USERS:
            goodput = final_mean(resample(bundle.user_goodput[user], grid) / 1e6, window_start)
            row[f"user_{user}_goodput_mbps"] = goodput
            row[f"user_{user}_total_cwnd_packets"] = final_mean(
                total_series(bundle.subflow_cwnd[user], grid, MSS_BYTES), window_start
            )
            goodputs.append(goodput)
        aggregate = float(np.sum(goodputs))
        row["aggregate_goodput_mbps"] = aggregate
        row["jain_fairness"] = jain(np.asarray(goodputs))
        row["a_vs_bc_mean_ratio"] = goodputs[0] / float(np.mean(goodputs[1:])) if np.mean(goodputs[1:]) > 0 else 0.0
        row["aggregate_path_utilization"] = aggregate / TOTAL_PATH_CAPACITY_MBPS
        for path in PATH_QUEUE_MODULES:
            row[f"path_{path}_queue_packets"] = final_mean(resample(bundle.queues[path], grid, True), window_start)
        row["shared_queue_packets"] = float(np.mean([row[f"path_{path}_queue_packets"] for path in range(1, 5)]))
        row["private_queue_packets"] = float(np.mean([row[f"path_{path}_queue_packets"] for path in range(5, 9)]))
        rows.append(row)
    return pd.DataFrame(rows)


def save_user_goodput_timeseries(bundles: list[Bundle], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(len(bundles), 1, figsize=(10, 9), sharex=True, sharey=True)
    axes = np.atleast_1d(axes)
    for ax, bundle in zip(axes, bundles):
        for user, _index, paths in USERS:
            ax.plot(grid, resample(bundle.user_goodput[user], grid) / 1e6, label=f"{user}: {paths}")
        ax.set_title(bundle.label)
        ax.set_ylabel("Mbps")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle("Per-Connection Goodput")
    fig.tight_layout()
    fig.savefig(out_dir / "per_user_goodput_timeseries.pdf")
    plt.close(fig)


def save_subflow_timeseries(bundles: list[Bundle], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(len(bundles), len(USERS), figsize=(14, 10), sharex=True, sharey=True)
    axes = np.asarray(axes).reshape(len(bundles), len(USERS))
    for row, bundle in enumerate(bundles):
        for col, (user, _index, paths) in enumerate(USERS):
            ax = axes[row, col]
            for sf, series in enumerate(bundle.subflow_throughput[user], start=1):
                ax.plot(grid, resample(series, grid) / 1e6, label=f"sf {sf}")
            ax.set_title(f"{bundle.label}: {user}\n{paths}")
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


def save_cwnd_timeseries(bundles: list[Bundle], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(len(bundles), len(USERS), figsize=(14, 10), sharex=True, sharey=True)
    axes = np.asarray(axes).reshape(len(bundles), len(USERS))
    for row, bundle in enumerate(bundles):
        for col, (user, _index, _paths) in enumerate(USERS):
            ax = axes[row, col]
            for sf, series in enumerate(bundle.subflow_cwnd[user], start=1):
                ax.plot(grid, resample(series, grid) / MSS_BYTES, label=f"sf {sf}")
            ax.set_title(f"{bundle.label}: connection {user}")
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


def save_queue_timeseries(bundles: list[Bundle], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(len(bundles), 1, figsize=(11, 9), sharex=True, sharey=True)
    axes = np.atleast_1d(axes)
    for ax, bundle in zip(axes, bundles):
        for path in PATH_QUEUE_MODULES:
            kind = "shared" if path <= 4 else "private"
            ax.plot(grid, resample(bundle.queues[path], grid, True), label=f"path {path} ({kind})")
        ax.set_title(bundle.label)
        ax.set_ylabel("Packets")
        ax.grid(True, alpha=0.3)
        ax.legend(ncol=4, fontsize=7)
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle("Per-Path Forward Queue Occupancy")
    fig.tight_layout()
    fig.savefig(out_dir / "per_path_queue_occupancy_timeseries.pdf")
    plt.close(fig)


def save_jain_timeseries(bundles: list[Bundle], grid: np.ndarray, out_dir: Path) -> None:
    plt.figure(figsize=(9, 4.5))
    for bundle in bundles:
        plt.plot(grid, jain_timeseries(bundle, grid), label=bundle.label)
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
        axes[0].bar(x + offset, summary[f"user_{user}_goodput_mbps"], width, label=f"connection {user}")
    axes[0].set_title("Per-Connection Goodput")
    axes[0].set_ylabel("Mbps")
    axes[0].legend(fontsize=8)
    axes[1].bar(x, summary["jain_fairness"])
    axes[1].set_title("Jain Fairness")
    axes[1].set_ylim(0.75, 1.01)
    axes[2].bar(x, summary["a_vs_bc_mean_ratio"])
    axes[2].axhline(1.0, color="black", linestyle="--", linewidth=1)
    axes[2].set_title("A / Mean(B,C)")
    for ax in axes:
        ax.set_xticks(x, labels, rotation=20, ha="right")
        ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "fairness_and_goodput_summary.pdf")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    axes[0].bar(x - width / 2, summary["shared_queue_packets"], width, label="shared paths 1-4")
    axes[0].bar(x + width / 2, summary["private_queue_packets"], width, label="private paths 5-8")
    axes[0].set_title("Mean Queue Occupancy")
    axes[0].set_ylabel("Packets")
    axes[0].legend(fontsize=8)
    axes[1].bar(x, summary["aggregate_goodput_mbps"])
    axes[1].set_title("Aggregate Goodput")
    axes[1].set_ylabel("Mbps")
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


def save_protocol_plots(bundle: Bundle, out_root: Path) -> None:
    out_dir = out_root / "by_protocol" / bundle.protocol
    out_dir.mkdir(parents=True, exist_ok=True)
    grid = common_grid([bundle])
    if len(grid) == 0:
        return
    save_user_goodput_timeseries([bundle], grid, out_dir)
    save_subflow_timeseries([bundle], grid, out_dir)
    save_cwnd_timeseries([bundle], grid, out_dir)
    save_queue_timeseries([bundle], grid, out_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot mptcpExperiments experiment 2.")
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--final-window", type=float, default=60.0)
    args = parser.parse_args()

    sim_root = Path(__file__).resolve().parents[2]
    csv_root = sim_root / "experiments" / "experiment2" / "csvs"
    out_dir = sim_root / "plots" / "experiment2"
    shutil.rmtree(out_dir, ignore_errors=True)
    aggregate_dir = out_dir / "aggregate"
    aggregate_dir.mkdir(parents=True, exist_ok=True)

    bundles = [
        bundle
        for protocol, label in PROTOCOLS
        if (bundle := load_bundle(csv_root, protocol, label, args.run)) is not None
    ]
    if not bundles:
        print(f"no extracted CSV data found under {csv_root}")
        return 1
    grid = common_grid(bundles)
    if len(grid) == 0:
        print("no usable timeseries data found")
        return 1

    summary = build_summary(bundles, args.final_window)
    summary.to_csv(out_dir / "summary_final_window.csv", index=False)
    summary.to_csv(aggregate_dir / "summary_final_window.csv", index=False)
    save_user_goodput_timeseries(bundles, grid, aggregate_dir)
    save_subflow_timeseries(bundles, grid, aggregate_dir)
    save_cwnd_timeseries(bundles, grid, aggregate_dir)
    save_queue_timeseries(bundles, grid, aggregate_dir)
    save_jain_timeseries(bundles, grid, aggregate_dir)
    save_aggregate_plots(summary, aggregate_dir)
    for bundle in bundles:
        save_protocol_plots(bundle, out_dir)

    print(f"wrote aggregate plots under {aggregate_dir}")
    print(f"wrote per-protocol plots under {out_dir / 'by_protocol'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
