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
from matplotlib.colors import Normalize

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plotHelpers import (
    HIGH_IS_GOOD_CMAP,
    LOW_IS_GOOD_CMAP,
    annotated_heatmap,
    mean_std_annotations,
    save_figure,
    target_closeness,
)

PROTOCOLS = [
    ("mporb", "MPORB Uncoupled"),
    ("mporb_semicoupled_alpha", "Alpha"),
    ("mporb_olia", "MPORB OLIA"),
    ("mporb_semicoupled_beta", "Beta"),
    ("mporb_semicoupled_delta", "Delta"),
    ("mporb_semicoupled_epsilon", "Epsilon"),
    ("mporb_semicoupled_zeta", "Zeta"),
    ("lia", "LIA"),
    ("olia", "OLIA"),
    ("balia", "BALIA"),
]
USERS = [
    ("A", 0, "shared paths 1-4"),
    ("B", 1, "shared 1-2, private 5-6"),
    ("C", 2, "shared 3-4, private 7-8"),
]
USER_PATH_IDS = {
    "A": (1, 2, 3, 4),
    "B": (1, 2, 5, 6),
    "C": (3, 4, 7, 8),
}
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
        if len(subflow_throughput[user]) != 4 or len(subflow_cwnd[user]) != 4:
            print(
                f"warning: incomplete {label} run{run} user {user}: "
                f"throughput subflows={len(subflow_throughput[user])}, "
                f"cwnd subflows={len(subflow_cwnd[user])}"
            )
            return None

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


def total_series(series: list[pd.Series], grid: np.ndarray, scale: float = 1.0) -> pd.Series:
    total = pd.Series(np.zeros_like(grid), index=grid)
    for item in series:
        total = total.add(resample(item, grid), fill_value=0)
    return total / scale


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
        row[f"path_{path}_post_join_queue_packets"] = final_mean(resample(bundle.queues[path], grid), analysis_start)
    row["shared_queue_packets"] = float(np.mean([row[f"path_{path}_queue_packets"] for path in range(1, 5)]))
    row["private_queue_packets"] = float(np.mean([row[f"path_{path}_queue_packets"] for path in range(5, 9)]))
    row["post_join_shared_queue_packets"] = float(
        np.mean([row[f"path_{path}_post_join_queue_packets"] for path in range(1, 5)])
    )
    row["post_join_private_queue_packets"] = float(
        np.mean([row[f"path_{path}_post_join_queue_packets"] for path in range(5, 9)])
    )
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


def post_join_grid(grid: np.ndarray, analysis_start: float) -> np.ndarray:
    filtered = grid[grid >= analysis_start]
    return filtered if len(filtered) else grid


def save_goodput_heatmap(
    summary: pd.DataFrame,
    out_dir: Path,
    combined_pdf: PdfPages,
) -> None:
    columns = [f"user_{user}_run_average_goodput_mbps" for user in ("A", "B", "C")]
    means = summary[columns].to_numpy(dtype=float).T
    deviations = summary[[f"{column}_std" for column in columns]].to_numpy(dtype=float).T
    equal_share = TOTAL_PATH_CAPACITY_MBPS / len(USERS)
    quality = target_closeness(means, equal_share)

    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    annotated_heatmap(
        ax,
        means,
        ["A", "B", "C"],
        summary["label"].tolist(),
        f"Closeness to equal share ({equal_share:.1f} Mbps)",
        annotations=mean_std_annotations(means, deviations),
        color_values=quality,
        cmap=HIGH_IS_GOOD_CMAP,
        norm=Normalize(vmin=0.0, vmax=1.0),
    )
    ax.set_title("Connection Goodput")
    ax.set_xlabel("Protocol")
    ax.set_ylabel("Main connection")
    save_figure(fig, out_dir / "goodput.pdf", combined_pdf)


def save_overview_plot(
    summary: pd.DataFrame,
    out_dir: Path,
    combined_pdf: PdfPages,
) -> None:
    labels = summary["label"].tolist()
    positions = np.arange(len(labels))
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.0), sharey=True)

    axes[0].errorbar(
        summary["run_average_aggregate_goodput_mbps"],
        positions,
        xerr=summary["run_average_aggregate_goodput_mbps_std"],
        fmt="o",
        capsize=3,
    )
    axes[0].axvline(TOTAL_PATH_CAPACITY_MBPS, color="black", linestyle="--", linewidth=1)
    axes[0].set_title("Aggregate Goodput")
    axes[0].set_xlabel("Mbps")

    axes[1].errorbar(
        summary["run_average_jain_fairness"],
        positions,
        xerr=summary["run_average_jain_fairness_std"],
        fmt="o",
        capsize=3,
    )
    axes[1].axvline(1.0, color="black", linestyle="--", linewidth=1)
    axes[1].set_xlim(0.75, 1.01)
    axes[1].set_title("Fairness")
    axes[1].set_xlabel("Jain index")

    axes[0].set_yticks(positions, labels)
    axes[0].invert_yaxis()
    for ax in axes:
        ax.grid(True, axis="x", alpha=0.3)
    save_figure(fig, out_dir / "overview.pdf", combined_pdf)


def save_queue_heatmap(
    summary: pd.DataFrame,
    out_dir: Path,
    combined_pdf: PdfPages,
) -> None:
    columns = [f"path_{path}_post_join_queue_packets" for path in PATH_QUEUE_MODULES]
    means = summary[columns].to_numpy(dtype=float).T
    deviations = summary[[f"{column}_std" for column in columns]].to_numpy(dtype=float).T
    fig, ax = plt.subplots(figsize=(10.5, 6.5))
    annotated_heatmap(
        ax,
        means,
        [str(path) for path in PATH_QUEUE_MODULES],
        summary["label"].tolist(),
        "Queue occupancy (packets)",
        annotations=mean_std_annotations(means, deviations, decimals=0),
        cmap=LOW_IS_GOOD_CMAP,
    )
    ax.set_title("Queues")
    ax.set_xlabel("Protocol")
    ax.set_ylabel("Path (1-4 shared, 5-8 private)")
    save_figure(fig, out_dir / "queues.pdf", combined_pdf)


def individual_output_dir(bundle: Bundle, out_root: Path) -> Path:
    out_dir = out_root / "individual" / bundle.protocol / f"run{bundle.run}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def save_individual_goodput_plot(
    bundle: Bundle,
    grid: np.ndarray,
    out_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    for user, _index, _description in USERS:
        values = resample(bundle.user_goodput[user], grid) / 1e6
        paths = ",".join(str(path) for path in USER_PATH_IDS[user])
        ax.plot(grid, values, label=f"{user} (paths {paths})")
    ax.set_title(f"{bundle.label}, Run {bundle.run}")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Goodput (Mbps)")
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=3, fontsize=8)
    save_figure(fig, out_dir / "goodput.pdf")


def save_individual_cwnd_plot(
    bundle: Bundle,
    grid: np.ndarray,
    out_dir: Path,
) -> None:
    fig, axes = plt.subplots(len(USERS), 1, figsize=(10.0, 8.0), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, (user, _index, _description) in zip(axes, USERS):
        for path, cwnd in zip(USER_PATH_IDS[user], bundle.subflow_cwnd[user]):
            ax.step(
                grid,
                resample(cwnd, grid) / MSS_BYTES,
                where="post",
                label=f"Path {path}",
            )
        ax.set_title(f"Connection {user}")
        ax.set_ylabel("cwnd (packets)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8, ncol=4)
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle(f"{bundle.label}, Run {bundle.run}")
    save_figure(fig, out_dir / "cwnd.pdf")


def save_individual_queue_plot(
    bundle: Bundle,
    grid: np.ndarray,
    out_dir: Path,
) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(10.0, 6.5), sharex=True, sharey=True)
    for ax, paths, title in (
        (axes[0], range(1, 5), "Shared paths"),
        (axes[1], range(5, 9), "Private paths"),
    ):
        for path in paths:
            ax.step(
                grid,
                resample(bundle.queues[path], grid),
                where="post",
                label=f"Path {path}",
            )
        ax.set_title(title)
        ax.set_ylabel("Packets")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8, ncol=4)
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle(f"{bundle.label}, Run {bundle.run}")
    save_figure(fig, out_dir / "queues.pdf")


def save_individual_plots(bundle: Bundle, out_root: Path, analysis_start: float) -> None:
    grid = post_join_grid(common_grid([bundle]), analysis_start)
    if len(grid) == 0:
        return
    out_dir = individual_output_dir(bundle, out_root)
    save_individual_goodput_plot(bundle, grid, out_dir)
    save_individual_cwnd_plot(bundle, grid, out_dir)
    save_individual_queue_plot(bundle, grid, out_dir)


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
    parser.add_argument(
        "--final-window",
        type=float,
        default=10.0,
        help="Duration of the steady-state summary window at the end of the run. Defaults to 10s.",
    )
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

    with PdfPages(out_dir / "aggregate.pdf") as combined_pdf:
        save_goodput_heatmap(summary, aggregate_dir, combined_pdf)
        save_overview_plot(summary, aggregate_dir, combined_pdf)
        save_queue_heatmap(summary, aggregate_dir, combined_pdf)
    for bundle in bundles:
        save_individual_plots(bundle, out_dir, args.analysis_start)

    print(f"wrote aggregate plots under {aggregate_dir}")
    print(f"wrote combined aggregate plots to {out_dir / 'aggregate.pdf'}")
    print(f"wrote per-run plots under {out_dir / 'individual'}")
    print(f"aggregated runs: {', '.join(str(run) for run in runs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
