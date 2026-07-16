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
    ("mporb", "MPORB Uncoupled"),
    ("mporb_alpha", "MPORB Alpha"),
    ("mporb_delta", "MPORB Delta"),
]
MSS_BYTES = 1448
RTT_SECONDS = 0.05
USERS_PER_TYPE = 4
USER_COUNT = 2 * USERS_PER_TYPE
BLUE_USERS = tuple(range(USERS_PER_TYPE))
RED_USERS = tuple(range(USERS_PER_TYPE, USER_COUNT))
X_CAPACITY_MBPS = 27.0
T_CAPACITY_MBPS = 36.0
IDEAL_PROBE_PER_CONNECTION_MBPS = MSS_BYTES * 8 / RTT_SECONDS / 1e6
IDEAL_TOTAL_PROBE_MBPS = USERS_PER_TYPE * IDEAL_PROBE_PER_CONNECTION_MBPS
IDEAL_AGGREGATE_MBPS = X_CAPACITY_MBPS + T_CAPACITY_MBPS - IDEAL_TOTAL_PROBE_MBPS
DEFAULT_RUNS = [1, 2, 3, 4, 5]
CONNECTIONS = {
    **{
        user: (f"Blue {user + 1}", ("x1: X", "x2: T"))
        for user in BLUE_USERS
    },
    **{
        user: (
            f"Red {user - USERS_PER_TYPE + 1}",
            ("y1: X then T", "y2: T"),
        )
        for user in RED_USERS
    },
}
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
    cwnd: dict[int, list[pd.Series]]
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


def load_subflows(run_root: Path, host: str, user: int, metric: str) -> list[pd.Series]:
    prefix = f"oliapareto.{host}[{user}].tcp.conn-"
    paths = [
        path
        for path in run_root.glob(f"*/{metric}.csv")
        if path.parent.name.startswith(prefix)
    ]
    series = [
        item
        for path in sorted(paths, key=conn_id)
        if (item := read_series(path, metric)) is not None and not item.empty
    ]
    return series[-2:]


def load_bundle(csv_root: Path, protocol: str, label: str, run: int) -> Bundle | None:
    run_root = csv_root / protocol / f"run{run}"
    goodput: dict[int, pd.Series] = {}
    subflows: dict[int, list[pd.Series]] = {}
    cwnd: dict[int, list[pd.Series]] = {}
    for user in range(USER_COUNT):
        app = read_series(run_root / f"oliapareto.server[{user}].app[0]" / "goodput.csv", "goodput")
        paths = load_subflows(run_root, "server", user, "throughput")
        windows = load_subflows(run_root, "client", user, "cwnd")
        if app is None or len(paths) != 2 or len(windows) != 2:
            print(
                f"warning: incomplete {label} run{run} user {user}: "
                f"goodput={app is not None}, throughput subflows={len(paths)}, "
                f"cwnd subflows={len(windows)}"
            )
            return None
        goodput[user] = app
        subflows[user] = paths
        cwnd[user] = windows

    queues: dict[str, pd.Series] = {}
    for name, module in QUEUE_MODULES.items():
        queue = read_series(run_root / module / "queueLength.csv", "queueLength")
        if queue is None:
            print(f"warning: missing {label} run{run} queue {name}")
            return None
        queues[name] = queue
    return Bundle(run, protocol, label, goodput, subflows, cwnd, queues)


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
        for windows in bundle.cwnd.values():
            series.extend(windows)
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

    connection_goodput = {
        user: mean_mbps(bundle.goodput[user], grid) for user in range(USER_COUNT)
    }
    blue_total = sum(connection_goodput[user] for user in BLUE_USERS)
    red_total = sum(connection_goodput[user] for user in RED_USERS)
    x1 = sum(mean_mbps(bundle.subflows[user][0], grid) for user in BLUE_USERS)
    x2 = sum(mean_mbps(bundle.subflows[user][1], grid) for user in BLUE_USERS)
    y1 = sum(mean_mbps(bundle.subflows[user][0], grid) for user in RED_USERS)
    y2 = sum(mean_mbps(bundle.subflows[user][1], grid) for user in RED_USERS)
    aggregate = blue_total + red_total
    row: dict[str, float | int | str] = {
        "run": bundle.run,
        "protocol": bundle.protocol,
        "label": bundle.label,
        "analysis_start_time_s": analysis_start,
        "analysis_end_time_s": float(grid.max()),
        "blue_total_goodput_mbps": blue_total,
        "red_total_goodput_mbps": red_total,
        "blue_mean_goodput_mbps": blue_total / USERS_PER_TYPE,
        "red_mean_goodput_mbps": red_total / USERS_PER_TYPE,
        "aggregate_goodput_mbps": aggregate,
        "aggregate_efficiency": aggregate / IDEAL_AGGREGATE_MBPS,
        "aggregate_loss_mbps": max(IDEAL_AGGREGATE_MBPS - aggregate, 0.0),
        "blue_x1_mbps": x1,
        "blue_x2_mbps": x2,
        "red_y1_mbps": y1,
        "red_y2_mbps": y2,
        "red_y1_excess_mbps": max(y1 - IDEAL_TOTAL_PROBE_MBPS, 0.0),
        "x_load_mbps": x1 + y1,
        "t_load_mbps": x2 + y1 + y2,
        "x_queue_packets": float(resample(bundle.queues["X"], grid).mean()),
        "t_queue_packets": float(resample(bundle.queues["T"], grid).mean()),
    }
    for user, goodput in connection_goodput.items():
        row[f"connection_{user}_goodput_mbps"] = goodput
    return row


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
    axes[1].axhline(
        IDEAL_TOTAL_PROBE_MBPS,
        color="black",
        linestyle="--",
        linewidth=1,
        label="Probe total",
    )
    axes[1].set_title("Inefficient Path")
    axes[1].set_ylabel("Total Red y1 goodput (Mbps)")
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
        ("blue_x1_mbps", "Blue x1 total: X"),
        ("blue_x2_mbps", "Blue x2 total: T"),
        ("red_y1_mbps", "Red y1 total: X then T"),
        ("red_y2_mbps", "Red y2 total: T"),
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


def population_mean_band(
    ax, grid: np.ndarray, groups: list[list[pd.Series]], label: str
) -> None:
    matrix = np.vstack(
        [
            sum(
                (resample(item, grid).to_numpy(dtype=float) for item in group),
                start=np.zeros_like(grid),
            )
            / (len(group) * 1e6)
            for group in groups
        ]
    )
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    ax.plot(grid, mean, label=label)
    ax.fill_between(grid, np.maximum(mean - std, 0), mean + std, alpha=0.18)


def save_connection_goodput_plots(
    grouped: dict[str, list[Bundle]], out_dir: Path
) -> None:
    all_bundles = [bundle for bundles in grouped.values() for bundle in bundles]
    grid = common_grid(all_bundles)
    if len(grid) == 0:
        return
    for user, (connection, _paths) in CONNECTIONS.items():
        fig, ax = plt.subplots(figsize=(9.5, 4.6))
        for protocol, label in PROTOCOLS:
            bundles = grouped.get(protocol, [])
            if bundles:
                band(ax, grid, [bundle.goodput[user] for bundle in bundles], label)
        ax.set_title(f"{connection} Connection Goodput")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Mbps")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        filename = connection.lower().replace(" ", "_")
        fig.savefig(out_dir / f"connection_{filename}_goodput.pdf")
        plt.close(fig)


def save_population_goodput_plot(
    grouped: dict[str, list[Bundle]], out_dir: Path
) -> None:
    all_bundles = [bundle for bundles in grouped.values() for bundle in bundles]
    grid = common_grid(all_bundles)
    if len(grid) == 0:
        return

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6), sharey=True)
    for protocol, label in PROTOCOLS:
        bundles = grouped.get(protocol, [])
        if not bundles:
            continue
        population_mean_band(
            axes[0],
            grid,
            [[bundle.goodput[user] for user in BLUE_USERS] for bundle in bundles],
            label,
        )
        population_mean_band(
            axes[1],
            grid,
            [[bundle.goodput[user] for user in RED_USERS] for bundle in bundles],
            label,
        )
    for ax, title in zip(axes, ("Blue Mean Goodput", "Red Mean Goodput")):
        ax.set_title(title)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Mbps per connection")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "population_goodput.pdf")
    plt.close(fig)


def save_individual_cwnd_plot(bundle: Bundle, out_root: Path) -> None:
    if not any(bundle.cwnd.values()):
        return
    out_dir = out_root / "by_protocol" / bundle.protocol / "runs" / f"run{bundle.run}"
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(4, 2, figsize=(14, 13), sharex=True)
    flat_axes = np.asarray(axes).reshape(-1)
    for ax, (user, (connection, path_labels)) in zip(flat_axes, CONNECTIONS.items()):
        for path_label, cwnd in zip(path_labels, bundle.cwnd[user]):
            ax.step(cwnd.index, cwnd.to_numpy(dtype=float) / MSS_BYTES, where="post", label=path_label)
        ax.set_title(connection)
        ax.set_ylabel("Packets")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    for ax in flat_axes[-2:]:
        ax.set_xlabel("Time (s)")
    fig.suptitle(f"{bundle.label} Run {bundle.run}: Subflow cwnd")
    fig.tight_layout()
    fig.savefig(out_dir / "subflow_cwnd.pdf")
    plt.close(fig)


def save_protocol_plots(protocol: str, label: str, bundles: list[Bundle], out_root: Path) -> None:
    out_dir = out_root / "by_protocol" / protocol
    out_dir.mkdir(parents=True, exist_ok=True)
    grid = common_grid(bundles)

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.5))
    sum_band(
        axes[0],
        grid,
        [[bundle.subflows[user][0] for user in RED_USERS] for bundle in bundles],
        "Red y1 total",
    )
    axes[0].axhline(
        IDEAL_TOTAL_PROBE_MBPS,
        color="black",
        linestyle="--",
        linewidth=1,
        label="Probe total",
    )
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
    parser.add_argument("--analysis-start", type=float, default=100.0)
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
    save_connection_goodput_plots(grouped, aggregate_dir)
    save_population_goodput_plot(grouped, aggregate_dir)
    for protocol, label in PROTOCOLS:
        if protocol in grouped:
            save_protocol_plots(protocol, label, grouped[protocol], out_dir)
    for bundle in bundles:
        save_individual_cwnd_plot(bundle, out_dir)

    print(f"wrote experiment 3 plots under {out_dir}")
    print(f"ideal aggregate goodput: {IDEAL_AGGREGATE_MBPS:.3f} Mbps")
    print(
        f"ideal total Red y1 probe rate: {IDEAL_TOTAL_PROBE_MBPS:.3f} Mbps "
        f"({IDEAL_PROBE_PER_CONNECTION_MBPS:.3f} Mbps per Red connection)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
