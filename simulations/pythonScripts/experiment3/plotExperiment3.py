#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import TwoSlopeNorm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plotHelpers import annotated_heatmap, mean_std_annotations, save_figure

PROTOCOLS = [
    ("lia", "LIA"),
    ("olia", "OLIA"),
    ("balia", "BALIA"),
    ("mporb", "MPORB Uncoupled"),
    ("mporb_alpha", "MPORB Alpha"),
    ("mporb_delta", "MPORB Delta"),
    ("mporb_epsilon", "MPORB Epsilon"),
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
PLOT_START = 10.0
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


def save_goodput_heatmap(
    summary: pd.DataFrame,
    out_dir: Path,
    combined_pdf: PdfPages,
) -> None:
    columns = [f"connection_{user}_goodput_mbps" for user in range(USER_COUNT)]
    means = summary[columns].to_numpy(dtype=float)
    deviations = summary[[f"{column}_std" for column in columns]].to_numpy(dtype=float)
    ideal_per_connection = IDEAL_AGGREGATE_MBPS / USER_COUNT
    maximum = max(float(np.nanmax(means)), ideal_per_connection * 1.35)
    norm = TwoSlopeNorm(vmin=0.0, vcenter=ideal_per_connection, vmax=maximum)
    connection_labels = [
        *(f"B{index + 1}" for index in range(USERS_PER_TYPE)),
        *(f"R{index + 1}" for index in range(USERS_PER_TYPE)),
    ]

    fig, ax = plt.subplots(figsize=(12.0, 5.4))
    annotated_heatmap(
        ax,
        means,
        summary["label"].tolist(),
        connection_labels,
        f"Goodput (Mbps), equal share = {ideal_per_connection:.2f}",
        annotations=mean_std_annotations(means, deviations, decimals=2),
        cmap="coolwarm",
        norm=norm,
    )
    ax.set_title("Connection Goodput")
    ax.set_xlabel("Main connection")
    save_figure(fig, out_dir / "goodput.pdf", combined_pdf)


def save_efficiency_plot(
    summary: pd.DataFrame,
    out_dir: Path,
    combined_pdf: PdfPages,
) -> None:
    labels = summary["label"].tolist()
    positions = np.arange(len(labels))
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.0), sharey=True)

    axes[0].errorbar(
        summary["aggregate_goodput_mbps"],
        positions,
        xerr=summary["aggregate_goodput_mbps_std"],
        fmt="o",
        capsize=3,
    )
    axes[0].axvline(IDEAL_AGGREGATE_MBPS, color="black", linestyle="--", linewidth=1)
    axes[0].set_title("Aggregate Goodput")
    axes[0].set_xlabel("Mbps")

    axes[1].errorbar(
        summary["red_y1_mbps"],
        positions,
        xerr=summary["red_y1_mbps_std"],
        fmt="o",
        capsize=3,
    )
    axes[1].axvline(IDEAL_TOTAL_PROBE_MBPS, color="black", linestyle="--", linewidth=1)
    axes[1].set_title("Inefficient Path")
    axes[1].set_xlabel("Red y1 total (Mbps)")

    axes[0].set_yticks(positions, labels)
    axes[0].invert_yaxis()
    for ax in axes:
        ax.grid(True, axis="x", alpha=0.3)
    save_figure(fig, out_dir / "efficiency.pdf", combined_pdf)


def save_path_heatmap(
    summary: pd.DataFrame,
    out_dir: Path,
    combined_pdf: PdfPages,
) -> None:
    columns = ["blue_x1_mbps", "blue_x2_mbps", "red_y1_mbps", "red_y2_mbps"]
    means = summary[columns].to_numpy(dtype=float)
    deviations = summary[[f"{column}_std" for column in columns]].to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(9.5, 5.3))
    annotated_heatmap(
        ax,
        means,
        summary["label"].tolist(),
        ["Blue x1\nX", "Blue x2\nT", "Red y1\nX then T", "Red y2\nT"],
        "Population subflow goodput (Mbps)",
        annotations=mean_std_annotations(means, deviations, decimals=2),
        cmap="magma",
    )
    ax.set_title("Path Allocation")
    save_figure(fig, out_dir / "path_allocation.pdf", combined_pdf)


def save_queue_heatmap(
    summary: pd.DataFrame,
    out_dir: Path,
    combined_pdf: PdfPages,
) -> None:
    columns = ["x_queue_packets", "t_queue_packets"]
    means = summary[columns].to_numpy(dtype=float)
    deviations = summary[[f"{column}_std" for column in columns]].to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    annotated_heatmap(
        ax,
        means,
        summary["label"].tolist(),
        ["X", "T"],
        "Queue occupancy (packets)",
        annotations=mean_std_annotations(means, deviations, decimals=1),
        cmap="magma",
    )
    ax.set_title("Queues")
    ax.set_xlabel("Bottleneck")
    save_figure(fig, out_dir / "queues.pdf", combined_pdf)


def individual_output_dir(bundle: Bundle, out_root: Path) -> Path:
    out_dir = out_root / "individual" / bundle.protocol / f"run{bundle.run}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def individual_grid(bundle: Bundle) -> np.ndarray:
    grid = common_grid([bundle])
    filtered = grid[grid >= PLOT_START]
    return filtered if len(filtered) else grid


def save_individual_goodput_plot(
    bundle: Bundle,
    grid: np.ndarray,
    out_dir: Path,
) -> None:
    ideal_per_connection = IDEAL_AGGREGATE_MBPS / USER_COUNT
    fig, axes = plt.subplots(2, 1, figsize=(10.0, 7.0), sharex=True, sharey=True)
    for ax, users, title in (
        (axes[0], BLUE_USERS, "Blue connections"),
        (axes[1], RED_USERS, "Red connections"),
    ):
        for user in users:
            label = CONNECTIONS[user][0]
            ax.plot(grid, resample(bundle.goodput[user], grid) / 1e6, label=label)
        ax.axhline(ideal_per_connection, color="black", linestyle="--", linewidth=1)
        ax.set_title(title)
        ax.set_ylabel("Goodput (Mbps)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8, ncol=4)
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle(f"{bundle.label}, Run {bundle.run}")
    save_figure(fig, out_dir / "goodput.pdf")


def save_individual_cwnd_plot(
    bundle: Bundle,
    grid: np.ndarray,
    out_dir: Path,
) -> None:
    fig, axes = plt.subplots(4, 2, figsize=(13.0, 12.0), sharex=True)
    flat_axes = np.asarray(axes).reshape(-1)
    for ax, (user, (connection, path_labels)) in zip(flat_axes, CONNECTIONS.items()):
        for path_label, cwnd in zip(path_labels, bundle.cwnd[user]):
            ax.step(
                grid,
                resample(cwnd, grid) / MSS_BYTES,
                where="post",
                label=path_label,
            )
        ax.set_title(connection)
        ax.set_ylabel("cwnd (packets)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    for ax in flat_axes[-2:]:
        ax.set_xlabel("Time (s)")
    fig.suptitle(f"{bundle.label}, Run {bundle.run}")
    save_figure(fig, out_dir / "cwnd.pdf")


def save_individual_queue_plot(
    bundle: Bundle,
    grid: np.ndarray,
    out_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    for name in ("X", "T"):
        ax.step(grid, resample(bundle.queues[name], grid), where="post", label=name)
    ax.set_title(f"{bundle.label}, Run {bundle.run}")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Queue occupancy (packets)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    save_figure(fig, out_dir / "queues.pdf")


def save_individual_plots(bundle: Bundle, out_root: Path) -> None:
    grid = individual_grid(bundle)
    if len(grid) == 0:
        return
    out_dir = individual_output_dir(bundle, out_root)
    save_individual_goodput_plot(bundle, grid, out_dir)
    save_individual_cwnd_plot(bundle, grid, out_dir)
    save_individual_queue_plot(bundle, grid, out_dir)


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
    with PdfPages(out_dir / "aggregate.pdf") as combined_pdf:
        save_goodput_heatmap(summary, aggregate_dir, combined_pdf)
        save_efficiency_plot(summary, aggregate_dir, combined_pdf)
        save_path_heatmap(summary, aggregate_dir, combined_pdf)
        save_queue_heatmap(summary, aggregate_dir, combined_pdf)
    for bundle in bundles:
        save_individual_plots(bundle, out_dir)

    print(f"wrote experiment 3 plots under {out_dir}")
    print(f"wrote combined aggregate plots to {out_dir / 'aggregate.pdf'}")
    print(f"ideal aggregate goodput: {IDEAL_AGGREGATE_MBPS:.3f} Mbps")
    print(
        f"ideal total Red y1 probe rate: {IDEAL_TOTAL_PROBE_MBPS:.3f} Mbps "
        f"({IDEAL_PROBE_PER_CONNECTION_MBPS:.3f} Mbps per Red connection)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
